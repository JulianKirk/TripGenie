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

import json
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


class StubItinerary:
    """Student 1's API, stateful enough to hold transport selections.

    Selections live over there now, so a UI test that ticks a trip and then
    reads the page back has to see its own write.
    """

    def __init__(self) -> None:
        self.pins: dict[tuple[str, str], dict[str, object]] = {}

    def pin(self, trip_id: str, transport_id: str, travellers: int = 2) -> None:
        self.pins[(trip_id, transport_id)] = {
            "trip_id": trip_id,
            "transport_id": transport_id,
            "traveller_count": travellers,
            "plan_status": "pending",
            "added_on": "2026-01-01",
            "notes": None,
        }

    @staticmethod
    def _data(payload: object) -> httpx.Response:
        return httpx.Response(200, json={"data": payload})

    @staticmethod
    def _missing() -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "no", "details": []}},
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        parts = [part for part in request.url.path.split("/") if part]
        known = {trip["id"] for trip in STUB_TRIPS}

        if len(parts) == 2 and parts[-1] == "trips":
            return self._data(STUB_TRIPS)

        if parts[-1] == "transport-traveller-totals":
            totals: dict[str, int] = {}
            for pin in self.pins.values():
                if pin["plan_status"] == "cancelled":
                    continue
                key = str(pin["transport_id"])
                totals[key] = totals.get(key, 0) + int(pin["traveller_count"])
            return self._data(
                [
                    {"transport_id": key, "travellers": value}
                    for key, value in sorted(totals.items())
                ],
            )

        if len(parts) == 4 and parts[1] == "transport" and parts[3] == "trips":
            holding = {t for (t, o) in self.pins if o == parts[2]}
            return self._data([t for t in STUB_TRIPS if t["id"] in holding])

        if len(parts) == 4 and parts[1] == "trips" and parts[3] == "transport":
            if parts[2] not in known:
                return self._missing()
            return self._data(
                [
                    dict(pin)
                    for (trip_id, _), pin in sorted(self.pins.items())
                    if trip_id == parts[2]
                ],
            )

        if len(parts) == 5 and parts[1] == "trips" and parts[3] == "transport":
            trip_id, transport_id = parts[2], parts[4]
            if trip_id not in known:
                return self._missing()
            if request.method == "PUT":
                body = json.loads(request.content or b"{}")
                record = {
                    "trip_id": trip_id,
                    "transport_id": transport_id,
                    "traveller_count": int(body["traveller_count"]),
                    "plan_status": str(body.get("plan_status") or "pending"),
                    "added_on": str(body.get("added_on") or "2026-01-01"),
                    "notes": body.get("notes"),
                }
                self.pins[(trip_id, transport_id)] = record
                return self._data(dict(record))
            if request.method == "DELETE":
                if self.pins.pop((trip_id, transport_id), None) is None:
                    return self._missing()
                return self._data({"id": transport_id, "deleted": True})

        if len(parts) == 3 and parts[1] == "trips":
            if parts[2] in known:
                return self._data({"id": parts[2]})
            return self._missing()

        return self._missing()


@pytest.fixture
def itinerary() -> StubItinerary:
    return StubItinerary()


@pytest.fixture
def trips_transport(itinerary: StubItinerary) -> httpx.MockTransport:
    """Stands in for Student 1's API, including transport selections."""
    return httpx.MockTransport(itinerary.handle)


@pytest.fixture
def unreachable_trips_transport() -> httpx.MockTransport:
    """A trips API that cannot be reached, so the picker must degrade."""

    def handler(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    return httpx.MockTransport(handler)


# A draft AI-Mode would return. The Adelaide bus is the cheapest seeded option
# and is always a candidate, so it is a safe id for the stub to name.
STUB_AI_DRAFT = {
    "overview": "The Adelaide airport bus at $6.50 per traveller is cheapest.",
    "suggestions": [
        {
            "transport_id": "transport_2027_adl_metro_bus",
            "reason": "Cheapest at $6.50 per traveller and only 35m.",
        },
    ],
    "considerations": ["Fares are tapped on board."],
    "disclaimer": "Advisory only. Review before adding to your trip.",
}


@pytest.fixture
def ai_transport() -> httpx.MockTransport:
    """Stands in for the shared AI-Mode service."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "run_ui_0001",
                    "correlation_id": "student3-transport-ui",
                    "model": "llama3.1:8b",
                    "provider": "ollama",
                    "response": json.dumps(STUB_AI_DRAFT),
                    "done": True,
                },
            },
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def unreachable_ai_transport() -> httpx.MockTransport:
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
    ai_transport: httpx.BaseTransport | None = None,
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
            ai_transport=ai_transport,
        )
        # Entering the backend TestClient runs its lifespan, which builds the
        # service the ASGITransport requests will look for on app.state.
        with TestClient(app):
            yield app


@pytest.fixture
def backend_app(
    database_path: Path,
    trips_transport: httpx.MockTransport,
) -> Iterator[object]:
    """Default backend: the itinerary service is reachable.

    It used to default to unreachable, which was reasonable while Student 1
    was only consulted to populate a picker. It is load-bearing now -- trip
    pages, seat counts and every selection go through it -- so an outage is a
    special case worth its own fixture rather than the default everything else
    is written against.
    """
    yield from _build_backend(database_path, trips_transport)


@pytest.fixture
def backend_app_with_trips(
    database_path: Path,
    trips_transport: httpx.MockTransport,
) -> Iterator[object]:
    yield from _build_backend(database_path, trips_transport)


@pytest.fixture
def backend_app_with_ai(
    database_path: Path,
    trips_transport: httpx.MockTransport,
    ai_transport: httpx.MockTransport,
) -> Iterator[object]:
    yield from _build_backend(database_path, trips_transport, ai_transport)


@pytest.fixture
def backend_app_without_ai(
    database_path: Path,
    trips_transport: httpx.MockTransport,
    unreachable_ai_transport: httpx.MockTransport,
) -> Iterator[object]:
    yield from _build_backend(
        database_path,
        trips_transport,
        unreachable_ai_transport,
    )


@pytest.fixture
def ai_client(
    frontend_settings: FrontendSettings,
    backend_app_with_ai: object,
) -> Iterator[TestClient]:
    """A frontend whose backend can reach a stubbed AI-Mode."""
    app = create_frontend_app(
        frontend_settings,
        transport=httpx.ASGITransport(app=backend_app_with_ai),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ai_down_client(
    frontend_settings: FrontendSettings,
    backend_app_without_ai: object,
) -> Iterator[TestClient]:
    app = create_frontend_app(
        frontend_settings,
        transport=httpx.ASGITransport(app=backend_app_without_ai),
    )
    with TestClient(app) as test_client:
        yield test_client


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
def backend_app_without_itinerary(
    database_path: Path,
    unreachable_trips_transport: httpx.MockTransport,
) -> Iterator[object]:
    yield from _build_backend(database_path, unreachable_trips_transport)


@pytest.fixture
def client_without_itinerary(
    frontend_settings: FrontendSettings,
    backend_app_without_itinerary: object,
) -> Iterator[TestClient]:
    """A frontend whose backend cannot reach the itinerary service."""
    app = create_frontend_app(
        frontend_settings,
        transport=httpx.ASGITransport(app=backend_app_without_itinerary),
    )
    with TestClient(app) as test_client:
        yield test_client


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
