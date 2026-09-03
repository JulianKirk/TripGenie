"""Liveness endpoint. Reports the database service behind this one, so a caller
can tell "the backend is down" from "the backend is up but its data is not"."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend_service.dependencies import (  # noqa: TC001  (runtime)
    DbDep,
    LocationDep,
)
from backend_service.schemas import HealthResponse

router = APIRouter(tags=["service"])
UNREACHABLE = "unreachable"


async def _status(health) -> str:
    """One upstream's status, or "unreachable".

    An unreachable upstream is a normal answer for this endpoint, not an error:
    the question asked is whether *this* service is running.
    """
    try:
        return (await health()).get("status", UNREACHABLE)
    except HTTPException:
        return UNREACHABLE


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, db: DbDep, location: LocationDep) -> HealthResponse:
    database = await _status(db.health)
    # Reported separately: without its data this service serves nothing, and
    # without the shared service it serves rows that cannot say where they are.
    # Two different kinds of broken deserve two different answers.
    shared = await _status(location.health)
    return HealthResponse(
        status="ok" if database == "ok" == shared else "degraded",
        service=request.app.state.settings.service_name,
        database=database,
        location=shared,
    )
