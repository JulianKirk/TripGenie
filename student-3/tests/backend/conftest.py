from __future__ import annotations

import json
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


def ai_generate_response(draft: dict[str, object]) -> httpx.Response:
    """AI-Mode's envelope around a model reply.

    The reply body is a JSON *string*, exactly as the provider returns it, so
    tests exercise the same parse path production uses.
    """
    return httpx.Response(
        200,
        json={
            "data": {
                "run_id": "run_test_0001",
                "correlation_id": "student3-transport-test",
                "model": "llama3.1:8b",
                "provider": "ollama",
                "response": json.dumps(draft),
                "done": True,
            },
        },
    )


def make_ai_transport(draft: dict[str, object]) -> httpx.MockTransport:
    """An AI-Mode that returns one fixed draft."""

    def handler(request: httpx.Request) -> httpx.Response:
        return ai_generate_response(draft)

    return httpx.MockTransport(handler)


def make_ai_error_transport(status_code: int, code: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "code": code,
                    "message": "AI-Mode said no.",
                    "details": [{"field": "ai_mode", "issue": "stubbed failure"}],
                },
            },
        )

    return httpx.MockTransport(handler)


def make_ai_unreachable_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    return httpx.MockTransport(handler)


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
    itinerary_transport: httpx.MockTransport,
) -> Iterator[TestClient]:
    app = create_app(
        settings,
        transport=database_transport,
        trips_transport=itinerary_transport,
    )
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


class FakeItineraryApi:
    """Student 1's public API, as this service uses it.

    Stateful on purpose: transport selections live over there now, so a test
    that attaches an option and then reads the seat count has to see its own
    write. A stateless stub would make the interesting assertions impossible.
    """

    TRIPS = (
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
    )

    def __init__(self) -> None:
        # (trip_id, transport_id) -> pin
        self.pins: dict[tuple[str, str], dict[str, object]] = {}

    # ------------------------------------------------------------- helpers

    def pin(
        self,
        trip_id: str,
        transport_id: str,
        travellers: int,
        status: str = "pending",
    ) -> None:
        """Seed a selection without going through HTTP."""
        self.pins[(trip_id, transport_id)] = {
            "trip_id": trip_id,
            "transport_id": transport_id,
            "traveller_count": travellers,
            "plan_status": status,
            "added_on": "2026-01-01",
            "notes": None,
        }

    @staticmethod
    def _data(payload: object, status_code: int = 200) -> httpx.Response:
        return httpx.Response(status_code, json={"data": payload})

    @staticmethod
    def _missing(what: str) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"{what} was not found.",
                    "details": [],
                },
            },
        )

    # -------------------------------------------------------------- routing

    def handle(self, request: httpx.Request) -> httpx.Response:
        parts = [p for p in request.url.path.split("/") if p]
        method = request.method
        known = {trip["id"] for trip in self.TRIPS}

        if parts[-1] == "trips" and len(parts) == 2 and method == "GET":
            return self._data([dict(trip) for trip in self.TRIPS])

        if parts[-1] == "transport-traveller-totals" and method == "GET":
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

        # /api/transport/{id}/trips
        if len(parts) == 4 and parts[1] == "transport" and parts[3] == "trips":
            holding = {
                trip_id
                for (trip_id, transport_id) in self.pins
                if transport_id == parts[2]
            }
            return self._data(
                [dict(trip) for trip in self.TRIPS if trip["id"] in holding],
            )

        # /api/trips/{trip_id}/transport
        if len(parts) == 4 and parts[1] == "trips" and parts[3] == "transport":
            trip_id = parts[2]
            if trip_id not in known:
                return self._missing(f"Trip '{trip_id}'")
            return self._data(
                [
                    dict(pin)
                    for (pinned, _), pin in sorted(self.pins.items())
                    if pinned == trip_id
                ],
            )

        # /api/trips/{trip_id}/transport/{transport_id}
        if len(parts) == 5 and parts[1] == "trips" and parts[3] == "transport":
            trip_id, transport_id = parts[2], parts[4]
            if trip_id not in known:
                return self._missing(f"Trip '{trip_id}'")
            if method == "PUT":
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
            if method == "DELETE":
                if self.pins.pop((trip_id, transport_id), None) is None:
                    return self._missing(f"Trip transport '{transport_id}'")
                return self._data({"id": transport_id, "deleted": True})

        # A trip existence check.
        if len(parts) == 3 and parts[1] == "trips":
            if parts[2] in known:
                return self._data({"id": parts[2]})
            return self._missing(f"Trip '{parts[2]}'")

        return self._missing(request.url.path)


@pytest.fixture
def itinerary_api() -> FakeItineraryApi:
    return FakeItineraryApi()


@pytest.fixture
def itinerary_transport(itinerary_api: FakeItineraryApi) -> httpx.MockTransport:
    return httpx.MockTransport(itinerary_api.handle)


@pytest.fixture
def known_trips_transport() -> httpx.MockTransport:
    """Stand in for Student 1's trips API, answering for KNOWN_TRIP_IDS."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trips"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": trip_id,
                            "name": "Queenstown Ski Escape",
                            "destination": "Queenstown",
                            "start_date": "2027-07-10",
                            "end_date": "2027-07-16",
                            "traveller_count": 3,
                            "status": "planned",
                            "notes": None,
                        }
                        for trip_id in sorted(KNOWN_TRIP_IDS)
                    ],
                },
            )

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
