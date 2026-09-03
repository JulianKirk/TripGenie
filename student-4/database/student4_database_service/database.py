"""SQLAlchemy engine and request-session setup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from student4_database_service.models import Base

if TYPE_CHECKING:
    import sqlite3

    from sqlalchemy.engine import Engine

    from student4_database_service.config import Settings


def _unicode_casefold(value: str | None) -> str | None:
    return None if value is None else value.casefold()


def _configure_sqlite(connection: sqlite3.Connection, _record: Any) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    connection.create_function(
        "unicode_casefold", 1, _unicode_casefold, deterministic=True
    )


def create_engine_and_session(
    settings: Settings,
) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(settings.database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _configure_sqlite)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
