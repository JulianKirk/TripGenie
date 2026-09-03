"""The public HTTP face of the shared reference service.

Its callers are the other students' backend services; it is in turn the only
caller of the shared reference database service. See
../../docs/backend-service-api.md for the contract.

The endpoints live in `routers/`, one module per resource; this file only wires
them together and owns the database client's lifetime.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from shared_backend_service import errors
from shared_backend_service.client import DatabaseClient
from shared_backend_service.config import Settings
from shared_backend_service.routers import currency, health, location

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app(settings: Settings | None = None, *, transport: Any = None) -> FastAPI:
    """`transport` seams the database service: the tests point it at the real
    database app over ASGI, or at a mock for the failures a working one will
    not produce on demand."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = DatabaseClient(settings, transport=transport)
        app.state.settings = settings
        app.state.db = db
        yield
        await db.aclose()

    app = FastAPI(title="Shared Reference Backend Service", lifespan=lifespan)
    errors.register(app)
    for router in (health, location, currency):
        app.include_router(router.router)
    return app


app = create_app()
