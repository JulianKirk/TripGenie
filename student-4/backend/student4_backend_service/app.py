from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx  # noqa: TC002 (public transport test seam)
from fastapi import FastAPI, HTTPException, Response, status

from . import errors
from .activity_routes import router as activity_router
from .ai_mode_client import AiModeClient
from .client import DatabaseClient
from .config import Settings
from .dependencies import DbDep, LocationDep  # noqa: TC001 (FastAPI runtime)
from .itinerary_client import ItineraryClient
from .itinerary_routes import router as itinerary_router
from .location_client import LocationClient
from .recommendation_routes import router as recommendation_router
from .recommendation_routes import trip_router
from .schemas import HealthResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from .schemas import DependencyHealth


def create_app(
    settings: Settings | None = None,
    *,
    database_transport: httpx.AsyncBaseTransport | None = None,
    location_transport: httpx.AsyncBaseTransport | None = None,
    itinerary_transport: httpx.AsyncBaseTransport | None = None,
    ai_mode_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.db = DatabaseClient(settings, transport=database_transport)
        app.state.location = LocationClient(settings, transport=location_transport)
        app.state.itinerary = ItineraryClient(settings, transport=itinerary_transport)
        app.state.ai = AiModeClient(settings, transport=ai_mode_transport)
        yield
        await app.state.db.aclose()
        await app.state.location.aclose()
        await app.state.itinerary.aclose()
        await app.state.ai.aclose()

    app = FastAPI(title="Activities and Attractions Backend Service", lifespan=lifespan)
    errors.register(app)

    async def state(call: Callable[[], Awaitable[DependencyHealth]]) -> str:
        try:
            return (await call()).status
        except HTTPException:
            return "unreachable"

    @app.get("/health", response_model=HealthResponse)
    async def health(db: DbDep, location: LocationDep) -> HealthResponse:
        database = await state(db.health)
        shared = await state(location.health)
        return HealthResponse(
            status="ok" if database == "ok" == shared else "degraded",
            service=settings.service_name,
            database=database,
            location=shared,
        )

    @app.get(
        "/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
    )
    async def ready(response: Response, db: DbDep) -> HealthResponse:
        database = await state(db.health)
        is_ready = database == "ok"
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="ready" if is_ready else "not_ready",
            service=settings.service_name,
            database=database,
            location="not_checked",
        )

    app.include_router(recommendation_router)
    app.include_router(trip_router)
    app.include_router(activity_router)
    app.include_router(itinerary_router)
    return app


app = create_app()
