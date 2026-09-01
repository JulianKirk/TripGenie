"""The public HTTP face of the accommodation service.

Its callers are the frontend and the other students' backend services; it is in
turn the only caller of the database service. See
../../docs/backend-service-api.md for the contract.

The endpoints live in `routers/`, one module per resource; this file only wires
them together and owns the database client's lifetime.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from backend_service import errors
from backend_service.client import DatabaseClient
from backend_service.config import Settings
from backend_service.itinerary_client import ItineraryClient
from backend_service.location_client import LocationClient
from backend_service.routers import accommodation, health, itinerary

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app(
    settings: Settings | None = None,
    *,
    transport: Any = None,
    itinerary_transport: Any = None,
    location_transport: Any = None,
) -> FastAPI:
    """One seam per upstream: `transport` for the database service,
    `itinerary_transport` for student 1's, `location_transport` for the shared
    reference service. They are separate because they are separate services --
    pointing two at one fake would make every call to the other a 404 against
    the wrong app."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = DatabaseClient(settings, transport=transport)
        itinerary_client = ItineraryClient(settings, transport=itinerary_transport)
        location_client = LocationClient(settings, transport=location_transport)
        app.state.settings = settings
        app.state.db = db
        app.state.itinerary = itinerary_client
        app.state.location = location_client
        yield
        await db.aclose()
        await itinerary_client.aclose()
        await location_client.aclose()

    app = FastAPI(title="Accommodation Backend Service", lifespan=lifespan)
    errors.register(app)
    for router in (health, accommodation, itinerary):
        app.include_router(router.router)
    return app


app = create_app()
