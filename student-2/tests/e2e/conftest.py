"""Fixtures for the accommodation end-to-end tests.

The default `client` wires the backend to the *real* database service over
ASGI -- a genuine HTTP round trip with no socket. That is what makes these
end-to-end: the two services declare the accommodation message separately (see
backend_service/schemas.py), so any drift between the two fails here rather
than in production.

The failures a working database service will not produce on demand -- a
timeout, a 500, a body that is not JSON -- are unit tested in tests/backend.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import Settings
from database_service.app import create_app as create_database_app
from database_service.config import Settings as DatabaseSettings

# The backend never dials this: every request goes through the injected
# transport. It only has to be a valid base URL.
DATABASE_URL = "http://database.test"


@pytest.fixture
def database(tmp_path):
    """The real database service, on a temporary SQLite file. Entering the
    TestClient runs its lifespan, which creates the schema."""
    app = create_database_app(
        DatabaseSettings(database_url=f"sqlite:///{tmp_path / 'accommodation.db'}")
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(database):
    app = create_app(
        Settings(database_url=DATABASE_URL),
        transport=httpx.ASGITransport(app=database.app),
    )
    with TestClient(app) as client:
        yield client
