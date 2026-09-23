from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .ai_mode_client import AiModeClient
from .config import Settings
from .errors import ApiError
from .models import (
    DataEnvelope,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    HealthPayload,
    QueryPayload,
    QueryRequest,
)
from .service import RagService

if TYPE_CHECKING:
    import httpx


def get_service(request: Request) -> RagService:
    return request.app.state.rag_service


def _error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                details=[ErrorDetail(**detail) for detail in exc.details],
            )
        ).model_dump(mode="json"),
    )


def create_app(
    settings: Settings | None = None,
    *,
    ai_mode_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ai_mode = AiModeClient(app_settings, transport=ai_mode_transport)
        app.state.rag_service = RagService(app_settings, ai_mode)
        try:
            yield
        finally:
            await ai_mode.close()

    app = FastAPI(
        title="TripGenie Shared RAG Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            ApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="One or more fields failed validation.",
                details=[
                    {
                        "field": ".".join(
                            str(item)
                            for item in error["loc"]
                            if item not in {"body", "query", "path"}
                        )
                        or "body",
                        "issue": str(error["msg"]).removeprefix("Value error, "),
                    }
                    for error in exc.errors()
                ],
            )
        )

    @app.get("/health", response_model=DataEnvelope[HealthPayload])
    async def health(
        service: Annotated[RagService, Depends(get_service)],
    ) -> dict[str, object]:
        return {"data": (await service.health()).model_dump(mode="json")}

    @app.get(
        "/ready",
        response_model=DataEnvelope[HealthPayload],
        responses={503: {"model": DataEnvelope[HealthPayload]}},
    )
    async def ready(
        service: Annotated[RagService, Depends(get_service)],
    ) -> JSONResponse:
        status_code, payload = await service.ready()
        return JSONResponse(
            status_code=status_code,
            content={"data": payload.model_dump(mode="json")},
        )

    @app.post("/query", response_model=DataEnvelope[QueryPayload])
    async def query(
        payload: QueryRequest,
        service: Annotated[RagService, Depends(get_service)],
    ) -> dict[str, object]:
        return {"data": (await service.query(payload)).model_dump(mode="json")}

    return app


app = create_app()
