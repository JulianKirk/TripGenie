"""Liveness endpoint. Reports the database service behind this one, so a caller
can tell "the backend is down" from "the backend is up but its data is not"."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend_service.dependencies import DbDep  # noqa: TC001  (runtime)
from backend_service.schemas import HealthResponse

router = APIRouter(tags=["service"])
UNREACHABLE = "unreachable"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, db: DbDep) -> HealthResponse:
    try:
        database = (await db.health()).get("status", UNREACHABLE)
    except HTTPException:
        # An unreachable database is a normal answer for this endpoint, not an
        # error: the question asked is whether *this* service is running.
        database = UNREACHABLE
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        service=request.app.state.settings.service_name,
        database=database,
    )
