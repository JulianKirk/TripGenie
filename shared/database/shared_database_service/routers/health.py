"""Liveness endpoint. Polled by CI after the container starts."""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared_database_service.schemas import HealthResponse

router = APIRouter(tags=["service"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    # ponytail: connect-and-close, no SELECT. Proves the database file opens;
    # does not prove the schema is there. That is fine because the lifespan
    # runs create_all -- a missing schema means no startup at all. Swap in a
    # real query if health ever has to mean "usable".
    with request.app.state.engine.connect():
        pass
    return HealthResponse(status="ok", service=request.app.state.settings.service_name)
