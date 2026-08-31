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
from backend_service.routers import accommodation, health

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app(settings: Settings | None = None, *, transport: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = DatabaseClient(settings, transport=transport)
        app.state.settings = settings
        app.state.db = db
        yield
        await db.aclose()

    app = FastAPI(title="Accommodation Backend Service", lifespan=lifespan)
    errors.register(app)
    for router in (health, accommodation):
        app.include_router(router.router)
    return app


app = create_app()
