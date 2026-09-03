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

# Trips Student 1 would report. Kept in step with their seed data so the trip
# picker is exercised against realistic identifiers and labels.
STUB_TRIPS = [
    {
        "id": "trip_2026_sydney_long_weekend",
        "name": "Sydney Long Weekend",
        "destination": "Sydney",
        "start_date": "2026-10-02",
        "end_date": "2026-10-05",
        "traveller_count": 2,
        "status": "planned",
        "notes": None,
    },
    {
        "id": "trip_2027_queenstown_ski_escape",
        "name": "Queenstown Ski Escape",
        "destination": "Queenstown",
        "start_date": "2027-07-10",
        "end_date": "2027-07-16",
        "traveller_count": 3,
        "status": "planned",
        "notes": None,
    },
]


@pytest.fixture
def trips_transport() -> httpx.MockTransport:
    """Stands in for Student 1's trips API, answering the directory lookup."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trips"):
            return httpx.Response(200, json={"data": STUB_TRIPS})

        trip_id = request.url.path.rsplit("/", 1)[-1]
        known = {trip["id"] for trip in STUB_TRIPS}
        if trip_id in known:
            return httpx.Response(200, json={"data": {"id": trip_id}})

        return httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "no", "details": []}},
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def unreachable_trips_transport() -> httpx.MockTransport:
    """A trips API that cannot be reached, so the picker must degrade."""

    def handler(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    return httpx.MockTransport(handler)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "tripgenie.db"


def _build_backend(
    database_path: Path,
    trips_transport: httpx.BaseTransport | None,
) -> Iterator[object]:
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
            trips_transport=trips_transport,
        )
        # Entering the backend TestClient runs its lifespan, which builds the
        # service the ASGITransport requests will look for on app.state.
        with TestClient(app):
            yield app


@pytest.fixture
def backend_app(
    database_path: Path,
    unreachable_trips_transport: httpx.MockTransport,
) -> Iterator[object]:
    """Default backend: Student 1 unreachable, so pickers degrade to text."""
    yield from _build_backend(database_path, unreachable_trips_transport)


@pytest.fixture
def backend_app_with_trips(
    database_path: Path,
    trips_transport: httpx.MockTransport,
) -> Iterator[object]:
    yield from _build_backend(database_path, trips_transport)


@pytest.fixture
def client_with_trips(
    frontend_settings: FrontendSettings,
    backend_app_with_trips: object,
) -> Iterator[TestClient]:
    """A frontend whose backend can reach Student 1's trips API."""
    app = create_frontend_app(
        frontend_settings,
        transport=httpx.ASGITransport(app=backend_app_with_trips),
    )
    with TestClient(app) as test_client:
        yield test_client


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
