"""Engine/session setup for the user microservice's SQLite DB."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database_service.models import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from database_service.config import Settings


def create_engine_and_session(
    settings: Settings,
) -> tuple[Engine, sessionmaker[Session]]:
    """Build the engine and its session factory, and create any missing tables.

    ponytail: create_all instead of Alembic -- one table, and there is no
    deployed data to migrate. Add migrations when there is.
    """
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)
