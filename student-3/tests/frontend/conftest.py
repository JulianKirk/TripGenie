"""Frontend tests run the whole Student 3 stack in-process.

Rather than stubbing the backend, these fixtures wire the real frontend to the
real backend to the real database. Every assertion therefore exercises the
genuine contracts, including validation messages and error envelopes, so the
templates cannot drift from what the services actually return.

The plumbing exists because the three tiers use different client styles: the
frontend client is async (``httpx.AsyncClient``) and the backend client is
synchronous, so the frontend reaches the backend through an ``ASGITransport``
while the backend reaches the database through a relay into its ``TestClient``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app as create_backend_app
from student3_backend_service.config import Settings as BackendSettings
from student3_database_service.app import create_app as create_database_app
from student3_database_service.config import Settings as DatabaseSettings
from student3_frontend_service.app import create_app as create_frontend_app
from student3_frontend_service.config import Settings as FrontendSettings

BACKEND_BASE_URL = "http://student-3-backend:8003"
DATABASE_BASE_URL = "http://student-3-database:8004"


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "tripgenie.db"


@pytest.fixture
def backend_app(database_path: Path) -> Iterator[object]:
    """The real backend, backed by the real database, both seeded."""
    database_app = create_database_app(DatabaseSettings(sqlite_path=database_path))
    with TestClient(database_app) as database_client:

        def relay(request: httpx.Request) -> httpx.Response:
            response = database_client.request(
                request.method,
                request.url.path,
                params=request.url.params,
                content=request.content or None,
                headers={"content-type": "application/json"},
            )
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers={
                    "content-type": response.headers.get(
                        "content-type",
                        "application/json",
                    ),
                },
            )

        app = create_backend_app(
            BackendSettings(database_api_base_url=DATABASE_BASE_URL),
            transport=httpx.MockTransport(relay),
        )
        # Entering the backend TestClient runs its lifespan, which builds the
        # service the ASGITransport requests will look for on app.state.
        with TestClient(app):
            yield app


@pytest.fixture
def frontend_settings() -> FrontendSettings:
    return FrontendSettings(backend_base_url=BACKEND_BASE_URL)


@pytest.fixture
def client(
    frontend_settings: FrontendSettings,
    backend_app: object,
) -> Iterator[TestClient]:
    app = create_frontend_app(
        frontend_settings,
        transport=httpx.ASGITransport(app=backend_app),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def offline_client(frontend_settings: FrontendSettings) -> Iterator[TestClient]:
    """A frontend whose backend cannot be reached at all."""

    async def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    app = create_frontend_app(
        frontend_settings,
        transport=httpx.MockTransport(refuse),
    )
    with TestClient(app) as test_client:
        yield test_client
