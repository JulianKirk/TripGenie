from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import ApiError
from .models import (
    DataEnvelope,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    GenerateRequest,
    GenerateResponsePayload,
    HealthResponse,
)
from .provider import OllamaProviderAdapter
from .service import VALIDATION_ERROR_MESSAGE, AiModeService


def _error_response(exc: ApiError) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            details=[ErrorDetail(**detail) for detail in exc.details],
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
    )


def _validation_detail_field(location: tuple[object, ...]) -> str:
    filtered = [str(part) for part in location if part not in {"body", "query", "path"}]
    if filtered:
        return ".".join(filtered)
    return str(location[-1]) if location else "body"


def envelope(payload: object) -> dict[str, object]:
    return {"data": payload}


def get_service(request: Request) -> AiModeService:
    return request.app.state.ai_mode_service


def create_app(
    settings: Settings | None = None,
    *,
    ollama_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        provider = OllamaProviderAdapter(app_settings, transport=ollama_transport)
        app.state.ai_mode_service = AiModeService(provider, app_settings)
        try:
            yield
        finally:
            await provider.close()

    app = FastAPI(
        title="TripGenie Release 0 AI-Mode Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "field": _validation_detail_field(tuple(error["loc"])),
                "issue": error["msg"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            ApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message=VALIDATION_ERROR_MESSAGE,
                details=details,
            )
        )

    @app.get("/health", response_model=DataEnvelope[HealthResponse])
    async def health(
        service: Annotated[AiModeService, Depends(get_service)],
    ) -> dict[str, object]:
        return envelope((await service.health()).model_dump(mode="json"))

    @app.get(
        "/ready",
        response_model=DataEnvelope[HealthResponse],
        responses={503: {"model": DataEnvelope[HealthResponse]}},
    )
    async def ready(
        service: Annotated[AiModeService, Depends(get_service)],
    ) -> JSONResponse:
        status_code, payload = await service.ready()
        return JSONResponse(
            status_code=status_code,
            content=envelope(payload.model_dump(mode="json")),
        )

    @app.post("/generate", response_model=DataEnvelope[GenerateResponsePayload])
    async def generate(
        payload: GenerateRequest,
        service: Annotated[AiModeService, Depends(get_service)],
    ) -> dict[str, object]:
        return envelope((await service.generate(payload)).model_dump(mode="json"))

    return app


app = create_app()
