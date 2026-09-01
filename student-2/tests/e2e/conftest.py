"""Fixtures for the accommodation end-to-end tests.

The default `client` wires the backend to the *real* database service and the
*real* shared reference service over ASGI -- genuine HTTP round trips with no
socket. That is what makes these end-to-end: each service declares its messages
separately (see backend_service/schemas.py), so any drift between them fails
here rather than in production. The shared service is in the chain because this
service stores places as ids and publishes them as names -- without it, half
the contract below is untested.

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
from shared_backend_service.app import create_app as create_shared_app
from shared_backend_service.config import Settings as SharedSettings
from shared_database_service.app import create_app as create_shared_database_app
from shared_database_service.config import Settings as SharedDatabaseSettings

# The backend never dials these: every request goes through an injected
# transport. They only have to be valid base URLs.
DATABASE_URL = "http://database.test"
LOCATION_URL = "http://location.test"


@pytest.fixture
def database(tmp_path):
    """The real database service, on a temporary SQLite file. Entering the
    TestClient runs its lifespan, which creates the schema."""
    app = create_database_app(
        DatabaseSettings(
            database_url=f"sqlite:///{tmp_path / 'accommodation.db'}", seed=False
        )
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def shared_database(tmp_path):
    """The real shared reference database service, seeded -- the places this
    service's rows point at have to exist for a name to come back."""
    app = create_shared_database_app(
        SharedDatabaseSettings(database_url=f"sqlite:///{tmp_path / 'location.db'}")
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def shared(shared_database):
    """The real shared reference backend, in front of its own database. Two
    hops, so the id-to-name path under test is the one that runs in compose."""
    app = create_shared_app(
        SharedSettings(database_url=LOCATION_URL),
        transport=httpx.ASGITransport(app=shared_database.app),
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(database, shared):
    app = create_app(
        Settings(database_url=DATABASE_URL, location_url=LOCATION_URL),
        transport=httpx.ASGITransport(app=database.app),
        location_transport=httpx.ASGITransport(app=shared.app),
    )
    with TestClient(app) as client:
        yield client
