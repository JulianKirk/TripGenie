"""The public HTTP face of the user service.

Its callers are the user frontend and, eventually, the other students' backend
services; it is in turn the only caller of the user database service. See
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
from backend_service.routers import health, user

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app(settings: Settings | None = None, *, transport: Any = None) -> FastAPI:
    """`transport` seams the database service: the tests point it at the
    database app over ASGI, or at a mock for the failures a real one will not
    produce on demand."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = DatabaseClient(settings, transport=transport)
        app.state.settings = settings
        app.state.db = db
        yield
        await db.aclose()

    app = FastAPI(title="User Backend Service", lifespan=lifespan)
    errors.register(app)
    for router in (health, user):
        app.include_router(router.router)
    return app


app = create_app()
