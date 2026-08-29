"""Engine/session setup for the accommodation microservice's SQLite DB."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared.backend.models import Base

DEFAULT_DATABASE_URL = "sqlite:///student-2/database/accommodation.db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def create_all() -> None:
    """Create all tables. Dev/test convenience -- use Alembic once schema
    migrations are actually needed."""
    import database.models  # noqa: F401  # registers accommodation tables on Base

    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
