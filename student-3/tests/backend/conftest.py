from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings
from student3_database_service.app import create_app as create_database_app
from student3_database_service.config import Settings as DatabaseSettings

TRIPS_BASE_URL = "http://student-1-backend:8001"


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "tripgenie.db"


@pytest.fixture
def database_settings(database_path: Path) -> DatabaseSettings:
    return DatabaseSettings(sqlite_path=database_path)


@pytest.fixture
def database_transport(
    database_settings: DatabaseSettings,
) -> Iterator[httpx.MockTransport]:
    """Run the real database service in-process behind the backend's client.

    Stubbing the database would let the backend drift from the service it
    actually talks to. Wiring the real app in means every backend test exercises
    the true contract, including its validation and error envelopes.

    The backend uses a synchronous ``httpx.Client``, so requests are relayed
    through the database service's own ``TestClient`` rather than an
    ``ASGITransport`` (which only implements the async path). Entering the
    TestClient also runs the database lifespan, which is what seeds the data.
    """
    database_app = create_database_app(database_settings)
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

        yield httpx.MockTransport(relay)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_api_base_url="http://student-3-database:8004",
        trips_api_base_url=TRIPS_BASE_URL,
    )


@pytest.fixture
def client(
    settings: Settings,
    database_transport: httpx.MockTransport,
) -> Iterator[TestClient]:
    app = create_app(settings, transport=database_transport)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def offline_client(settings: Settings) -> Iterator[TestClient]:
    """A backend whose database dependency always fails to connect."""

    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    app = create_app(settings, transport=httpx.MockTransport(refuse))
    with TestClient(app) as test_client:
        yield test_client


KNOWN_TRIP_IDS = frozenset({"trip_2027_queenstown_ski_escape"})


@pytest.fixture
def known_trips_transport() -> httpx.MockTransport:
    """Stand in for Student 1's trips API, answering for KNOWN_TRIP_IDS."""

    def handler(request: httpx.Request) -> httpx.Response:
        trip_id = request.url.path.rsplit("/", 1)[-1]
        if trip_id in KNOWN_TRIP_IDS:
            return httpx.Response(200, json={"data": {"id": trip_id}})

        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Trip '{trip_id}' was not found.",
                    "details": [],
                },
            },
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def unreachable_trips_transport() -> httpx.MockTransport:
    """A trips API that cannot be reached at all."""

    def handler(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    return httpx.MockTransport(handler)
