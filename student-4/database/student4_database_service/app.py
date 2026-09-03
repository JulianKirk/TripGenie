"""FastAPI composition root for the Student 4 database service."""

from __future__ import annotations

from contextlib import asynccontextmanager, suppress
from threading import Lock
from typing import TYPE_CHECKING

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from student4_database_service import errors
from student4_database_service.config import Settings
from student4_database_service.database import (
    create_engine_and_session,
    initialize_database,
)
from student4_database_service.routers import activity, health
from student4_database_service.seed_data import seed_database

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, session_factory = create_engine_and_session(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.database_initialized = False
        initialization_lock = Lock()

        def ensure_database_initialized() -> None:
            if app.state.database_initialized:
                return
            with initialization_lock:
                if app.state.database_initialized:
                    return
                initialize_database(engine)
                if settings.seed:
                    with session_factory() as session:
                        seed_database(session)
                app.state.database_initialized = True

        app.state.ensure_database_initialized = ensure_database_initialized
        with suppress(SQLAlchemyError):
            ensure_database_initialized()
        yield
        engine.dispose()

    app = FastAPI(
        title="Activities and Attractions Database Service", lifespan=lifespan
    )
    errors.register(app)
    app.include_router(health.router)
    app.include_router(activity.router)
    return app


app = create_app()
