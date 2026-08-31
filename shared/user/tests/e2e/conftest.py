"""Fixtures wiring the real backend to the real database service.

No mock transports here: the backend's httpx client is pointed at the actual
database app over ASGI, so both services' code runs. This is what catches drift
between the two independently-declared `schemas.py` files -- the thing every
other test suite deliberately fakes away.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import Settings
from database_service.app import create_app as create_database_app
from database_service.config import Settings as DatabaseSettings


@pytest.fixture
def database(tmp_path):
    """The database service, on its own temporary SQLite file. Unseeded: these
    tests create the accounts they assert on."""
    settings = DatabaseSettings(
        database_url=f"sqlite:///{tmp_path / 'user.db'}", seed=False
    )
    app = create_database_app(settings)
    # TestClient runs the lifespan, which is what builds the engine.
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(database):
    app = create_app(
        Settings(database_url="http://database.test"),
        transport=httpx.ASGITransport(app=database.app),
    )
    with TestClient(app) as client:
        yield client
