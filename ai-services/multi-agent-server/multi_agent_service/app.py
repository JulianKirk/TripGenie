from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from .agents import Agents
from .ai_mode_client import AiModeClient, AiModeError
from .config import Settings
from .errors import VALIDATION_ERROR_MESSAGE, ApiError
from .export import audit_document, audit_markdown
from .models import (
    DataEnvelope,
    DependencyStatus,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    HealthResponse,
    HistoryEvent,
    ReviewRequest,
    RunRecord,
    RunRequest,
    RunStatus,
    RunSummary,
)
from .store import RunStore, StoreError
from .workflow import WorkflowEngine

if TYPE_CHECKING:
    import httpx

RUN_ID = r"^magent_[0-9a-f]{12}$"
FEATURE = r"^[a-z0-9][a-z0-9-]{0,39}$"


def _error_response(exc: ApiError) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            details=[ErrorDetail(**detail) for detail in exc.details],
        ),
    )
    return JSONResponse(
        status_code=exc.status_code, content=body.model_dump(mode="json")
    )


def _validation_field(location: tuple[object, ...]) -> str:
    filtered = [str(part) for part in location if part not in {"body", "query", "path"}]
    if filtered:
        return ".".join(filtered)
    return str(location[-1]) if location else "body"


def envelope(payload: object) -> dict[str, object]:
    return {"data": payload}


def get_engine(request: Request) -> WorkflowEngine:
    return request.app.state.engine


def get_store(request: Request) -> RunStore:
    return request.app.state.store


EngineDep = Annotated[WorkflowEngine, Depends(get_engine)]
StoreDep = Annotated[RunStore, Depends(get_store)]
RunId = Annotated[str, Path(pattern=RUN_ID)]

router = APIRouter()


# ------------------------------------------------------------- operations


async def _health(request: Request) -> HealthResponse:
    store: RunStore = request.app.state.store
    ai_mode: AiModeClient = request.app.state.ai_mode
    settings: Settings = request.app.state.settings
    dependencies: dict[str, DependencyStatus] = {}
    try:
        store.ping()
        dependencies["store"] = DependencyStatus(
            status="ok", service="sqlite", detail="Run history is readable."
        )
    except StoreError as exc:
        dependencies["store"] = DependencyStatus(
            status="unavailable",
            service="sqlite",
            detail=str(exc),
            code="STORE_UNAVAILABLE",
        )
    try:
        ai_health = await ai_mode.health()
        ai_ok = ai_health.get("status") == "ok"
        dependencies["ai_mode"] = DependencyStatus(
            status="ok" if ai_ok else "degraded",
            service="ai-mode",
            detail="AI-Mode responded." if ai_ok else "AI-Mode reported a problem.",
        )
    except AiModeError as exc:
        dependencies["ai_mode"] = DependencyStatus(
            status="unavailable", service="ai-mode", detail=exc.message, code=exc.code
        )
    healthy = all(item.status == "ok" for item in dependencies.values())
    return HealthResponse(
        status="ok" if healthy else "degraded",
        service=settings.service_name,
        dependencies=dependencies,
        active_runs=request.app.state.engine.active_runs,
    )


@router.get("/health", response_model=DataEnvelope[HealthResponse])
async def health(request: Request) -> dict[str, object]:
    """Always 200: whether the process serves, and what it depends on."""
    return envelope((await _health(request)).model_dump(mode="json"))


@router.get(
    "/ready",
    response_model=DataEnvelope[HealthResponse],
    responses={503: {"model": DataEnvelope[HealthResponse]}},
)
async def ready(request: Request) -> JSONResponse:
    """200 only when runs can execute: the store works and AI-Mode is ok.

    A degraded AI-Mode (Ollama down, model missing) cannot run agents, so
    readiness needs every dependency fully ok.
    """
    payload = await _health(request)
    ready_now = payload.status == "ok"
    payload.status = "ready" if ready_now else "unavailable"
    return JSONResponse(
        status_code=200 if ready_now else 503,
        content=envelope(payload.model_dump(mode="json")),
    )


# ------------------------------------------------------------------- runs


@router.post("/runs", status_code=202, response_model=DataEnvelope[RunRecord])
async def start_run(payload: RunRequest, engine: EngineDep) -> dict[str, object]:
    """Start Planner → Worker → Reviewer in the background; poll the run."""
    return envelope((await engine.start(payload)).model_dump(mode="json"))


@router.get("/runs", response_model=DataEnvelope[list[RunSummary]])
async def list_runs(
    store: StoreDep,
    feature: Annotated[str | None, Query(pattern=FEATURE)] = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    runs = store.list_runs(feature=feature, status=status, limit=limit)
    return envelope([run.model_dump(mode="json") for run in runs])


@router.get("/runs/{run_id}", response_model=DataEnvelope[RunRecord])
async def get_run(run_id: RunId, engine: EngineDep) -> dict[str, object]:
    return envelope(engine.get(run_id).model_dump(mode="json"))


@router.post("/runs/{run_id}/review", response_model=DataEnvelope[RunRecord])
async def review_run(
    run_id: RunId,
    payload: ReviewRequest,
    engine: EngineDep,
) -> dict[str, object]:
    """Record the human's approve, correct, partial or reject decision."""
    return envelope(engine.review(run_id, payload).model_dump(mode="json"))


@router.get(
    "/runs/{run_id}/history",
    response_model=DataEnvelope[list[HistoryEvent]],
)
async def run_history(
    run_id: RunId,
    engine: EngineDep,
    store: StoreDep,
) -> dict[str, object]:
    engine.get(run_id)
    return envelope([event.model_dump(mode="json") for event in store.events(run_id)])


@router.get("/runs/{run_id}/export", response_model=None)
async def export_run(
    run_id: RunId,
    engine: EngineDep,
    store: StoreDep,
    output: Annotated[Literal["json", "markdown"], Query(alias="format")] = "json",
) -> JSONResponse | PlainTextResponse:
    """The run's workflow history and coordination/audit log, as evidence."""
    run = engine.get(run_id)
    events = store.events(run_id)
    if output == "markdown":
        return PlainTextResponse(
            audit_markdown(run, events), media_type="text/markdown"
        )
    return JSONResponse(content=envelope(audit_document(run, events)))


# -------------------------------------------------------------------- app


async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return _error_response(exc)


async def _validation_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "field": _validation_field(tuple(error["loc"])),
            "issue": str(error["msg"]).removeprefix("Value error, "),
        }
        for error in exc.errors()
    ]
    return _error_response(
        ApiError(422, "VALIDATION_ERROR", VALIDATION_ERROR_MESSAGE, details),
    )


def create_app(
    settings: Settings | None = None,
    *,
    ai_mode_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = RunStore(app_settings.db_path)
        store.fail_interrupted()
        ai_mode = AiModeClient(app_settings, transport=ai_mode_transport)
        app.state.settings = app_settings
        app.state.store = store
        app.state.ai_mode = ai_mode
        app.state.engine = WorkflowEngine(
            app_settings, store, Agents(app_settings, ai_mode)
        )
        try:
            yield
        finally:
            await app.state.engine.shutdown()
            await ai_mode.close()

    app = FastAPI(
        title="TripGenie Multi-Agent Server",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.include_router(router)
    return app


app = create_app()
