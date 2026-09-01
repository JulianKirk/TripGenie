"""HTTP wrapper around the shared reference database.

Internal-only: the shared backend service is the sole caller, so there is no
auth and no rate limiting here. See ../../docs/database-service-api.md for the
contract.

The endpoints live in `routers/`, one module per resource; this file only wires
them together and owns the engine's lifetime.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from shared_database_service import errors
from shared_database_service.config import Settings
from shared_database_service.database import create_engine_and_session
from shared_database_service.routers import currency, health, location
from shared_database_service.seed_data import seed

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, session_factory = create_engine_and_session(settings)
        if settings.seed:
            with session_factory() as session:
                seed(session)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        yield
        engine.dispose()

    app = FastAPI(title="Shared Reference Database Service", lifespan=lifespan)
    errors.register(app)
    for router in (health, location, currency):
        app.include_router(router.router)
    return app


app = create_app()
