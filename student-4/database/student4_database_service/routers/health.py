"""Database liveness endpoint."""

from fastapi import APIRouter, Request

from student4_database_service.schemas import HealthResponse

router = APIRouter(tags=["service"])


@router.get("/internal/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    request.app.state.ensure_database_initialized()
    with request.app.state.engine.connect():
        pass
    return HealthResponse(status="ok", service=request.app.state.settings.service_name)
