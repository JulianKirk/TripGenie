"""Shared fixtures for the user database service tests.

`database_service` is importable because shared/user is pip-installed (see
shared/user/pyproject.toml) -- no PYTHONPATH needed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database_service.app import create_app
from database_service.config import Settings
from database_service.models import Base, User
from database_service.repository import UserRepository


@pytest.fixture
def session():
    """Fresh in-memory SQLite DB per test -- no dependency on database.py."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def users(session):
    return UserRepository(session)


@pytest.fixture
def mark(users):
    return users.add(User(username="mark", password="hunter2"))


@pytest.fixture
def ada(users):
    return users.add(User(username="ada", password="difference-engine"))


@pytest.fixture
def client(tmp_path):
    """The internal API over a real (temporary) SQLite file -- the same path
    the container takes, minus the network.

    Seeding is off: these tests assert on exact counts of rows they created
    themselves, and the starter accounts would be two extra.
    """
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'user.db'}", seed=False)
    with TestClient(create_app(settings)) as client:
        yield client
