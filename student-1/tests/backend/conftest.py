from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy

import httpx
import pytest
from backend_service.app import create_app
from backend_service.config import Settings
from fastapi.testclient import TestClient


def create_trip_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Canberra Planning Sprint",
        "destination": "Canberra",
        "start_date": "2027-05-01",
        "end_date": "2027-05-04",
        "traveller_count": 2,
        "status": "planned",
        "notes": "Need a mix of museums and cafes.",
    }
    payload.update(overrides)
    return payload


def create_item_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "date": "2027-05-02",
        "start_time": "09:00",
        "end_time": "10:30",
        "title": "Museum Visit",
        "location": "National Museum of Australia",
        "description": "Start with the main collection.",
        "category": "activity",
        "notes": "Book tickets online.",
    }
    payload.update(overrides)
    return payload


def data_response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(status_code, json={"data": payload})


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            },
        },
    )


class FakeDatabaseApi:
    def __init__(self) -> None:
        self._trip_counter = 0
        self._item_counter = 0
        self.trip_create_calls = 0
        self.trip_update_calls = 0
        self.itinerary_item_list_requests: list[tuple[str, dict[str, str]]] = []
        self.requests: list[tuple[str, str]] = []
        self.trips: dict[str, dict[str, object]] = {
            "trip_2027_sydney_getaway": {
                "id": "trip_2027_sydney_getaway",
                "name": "Sydney Getaway",
                "destination": "Sydney",
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
                "traveller_count": 2,
                "status": "planned",
                "notes": "Keep ferry tickets handy.",
            },
            "trip_2027_tokyo_city_break": {
                "id": "trip_2027_tokyo_city_break",
                "name": "Tokyo City Break",
                "destination": "Tokyo",
                "start_date": "2027-05-10",
                "end_date": "2027-05-12",
                "traveller_count": 3,
                "status": "active",
                "notes": "Prioritise Asakusa and Shibuya.",
            },
        }
        self.items: dict[str, dict[str, object]] = {
            "item_2027_sydney_harbour_walk": {
                "id": "item_2027_sydney_harbour_walk",
                "trip_id": "trip_2027_sydney_getaway",
                "date": "2027-04-02",
                "start_time": "09:00",
                "end_time": "10:30",
                "title": "Harbour Walk",
                "location": "Circular Quay",
                "description": "Walk from Circular Quay to the Opera House.",
                "category": "activity",
                "notes": "Carry sunscreen.",
            },
            "item_2027_sydney_dinner": {
                "id": "item_2027_sydney_dinner",
                "trip_id": "trip_2027_sydney_getaway",
                "date": "2027-04-01",
                "start_time": "19:00",
                "end_time": "20:30",
                "title": "Waterside Dinner",
                "location": "Darling Harbour",
                "description": "Dinner after check-in.",
                "category": "meal",
                "notes": None,
            },
        }
        self.health_payload = {
            "status": "ok",
            "service": "student-1-database",
            "sqlite_path": "/data/student-1/tripgenie.db",
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path_parts = request.url.path.strip("/").split("/")
        method = request.method.upper()
        self.requests.append((method, request.url.path))

        if path_parts == ["internal", "health"] and method == "GET":
            return httpx.Response(200, json=self.health_payload)

        if path_parts == ["internal", "trips"]:
            if method == "GET":
                return data_response(200, self._list_trips(dict(request.url.params)))
            if method == "POST":
                return self._create_trip(request)

        if len(path_parts) == 3 and path_parts[:2] == ["internal", "trips"]:
            trip_id = path_parts[2]
            if method == "GET":
                return self._get_trip(trip_id)
            if method == "PATCH":
                return self._update_trip(trip_id, request)
            if method == "DELETE":
                return self._delete_trip(trip_id)

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["internal", "trips"]
            and path_parts[3] == "itinerary-items"
        ):
            trip_id = path_parts[2]
            if method == "GET":
                return self._list_items(trip_id, dict(request.url.params))
            if method == "POST":
                return self._create_item(trip_id, request)

        if len(path_parts) == 3 and path_parts[:2] == ["internal", "itinerary-items"]:
            item_id = path_parts[2]
            if method == "GET":
                return self._get_item(item_id)
            if method == "PATCH":
                return self._update_item(item_id, request)
            if method == "DELETE":
                return self._delete_item(item_id)

        return httpx.Response(404, json={"detail": "not found"})

    def _list_trips(self, params: dict[str, str]) -> list[dict[str, object]]:
        trips = list(self.trips.values())
        status_filter = params.get("status")
        destination = params.get("destination")
        if status_filter is not None:
            trips = [trip for trip in trips if trip["status"] == status_filter]
        if destination is not None:
            trips = [
                trip
                for trip in trips
                if str(trip["destination"]).lower() == destination.lower()
            ]

        return sorted(
            (deepcopy(trip) for trip in trips),
            key=lambda trip: (
                str(trip["start_date"]),
                str(trip["name"]).lower(),
                str(trip["id"]),
            ),
        )

    def _create_trip(self, request: httpx.Request) -> httpx.Response:
        self.trip_create_calls += 1
        payload = self._request_json(request)
        trip_id = str(payload.get("id") or self._next_trip_id())
        if trip_id in self.trips:
            return error_response(
                409,
                "CONFLICT",
                f"Trip '{trip_id}' already exists.",
                [{"field": "id", "issue": "already exists"}],
            )

        record = {
            "id": trip_id,
            "name": payload["name"],
            "destination": payload["destination"],
            "start_date": payload["start_date"],
            "end_date": payload["end_date"],
            "traveller_count": payload["traveller_count"],
            "status": payload["status"],
            "notes": payload.get("notes"),
        }
        self.trips[trip_id] = record
        return data_response(201, deepcopy(record))

    def _get_trip(self, trip_id: str) -> httpx.Response:
        record = self.trips.get(trip_id)
        if record is None:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        return data_response(200, deepcopy(record))

    def _update_trip(self, trip_id: str, request: httpx.Request) -> httpx.Response:
        self.trip_update_calls += 1
        record = self.trips.get(trip_id)
        if record is None:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        record.update(self._request_json(request))
        return data_response(200, deepcopy(record))

    def _delete_trip(self, trip_id: str) -> httpx.Response:
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        del self.trips[trip_id]
        self.items = {
            item_id: item
            for item_id, item in self.items.items()
            if item["trip_id"] != trip_id
        }
        return data_response(200, {"id": trip_id, "deleted": True})

    def _list_items(
        self,
        trip_id: str,
        params: dict[str, str],
    ) -> httpx.Response:
        self.itinerary_item_list_requests.append((trip_id, deepcopy(params)))
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        date_filter = params.get("date")
        category_filter = params.get("category")
        items = [
            item
            for item in self.items.values()
            if item["trip_id"] == trip_id
            and (date_filter is None or item["date"] == date_filter)
            and (category_filter is None or item["category"] == category_filter)
        ]
        ordered = sorted(
            (deepcopy(item) for item in items),
            key=lambda item: (
                str(item["date"]),
                1 if item["start_time"] is None else 0,
                "" if item["start_time"] is None else str(item["start_time"]),
                str(item["title"]).lower(),
                str(item["id"]),
            ),
        )
        return data_response(200, ordered)

    def _create_item(self, trip_id: str, request: httpx.Request) -> httpx.Response:
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        payload = self._request_json(request)
        item_id = str(payload.get("id") or self._next_item_id())
        if item_id in self.items:
            return error_response(
                409,
                "CONFLICT",
                f"Itinerary item '{item_id}' already exists.",
                [{"field": "id", "issue": "already exists"}],
            )

        record = {
            "id": item_id,
            "trip_id": trip_id,
            "date": payload["date"],
            "start_time": payload.get("start_time"),
            "end_time": payload.get("end_time"),
            "title": payload["title"],
            "location": payload.get("location"),
            "description": payload.get("description"),
            "category": payload["category"],
            "notes": payload.get("notes"),
        }
        self.items[item_id] = record
        return data_response(201, deepcopy(record))

    def _get_item(self, item_id: str) -> httpx.Response:
        record = self.items.get(item_id)
        if record is None:
            return error_response(
                404,
                "NOT_FOUND",
                f"Itinerary item '{item_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        return data_response(200, deepcopy(record))

    def _update_item(self, item_id: str, request: httpx.Request) -> httpx.Response:
        record = self.items.get(item_id)
        if record is None:
            return error_response(
                404,
                "NOT_FOUND",
                f"Itinerary item '{item_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        record.update(self._request_json(request))
        return data_response(200, deepcopy(record))

    def _delete_item(self, item_id: str) -> httpx.Response:
        if item_id not in self.items:
            return error_response(
                404,
                "NOT_FOUND",
                f"Itinerary item '{item_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        del self.items[item_id]
        return data_response(200, {"id": item_id, "deleted": True})

    def _next_trip_id(self) -> str:
        self._trip_counter += 1
        return f"trip_generated_{self._trip_counter:02d}"

    def _next_item_id(self) -> str:
        self._item_counter += 1
        return f"item_generated_{self._item_counter:02d}"

    @staticmethod
    def _request_json(request: httpx.Request) -> dict[str, object]:
        if not request.content:
            return {}

        return json.loads(request.content.decode("utf-8"))


class FakeOllamaApi:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._queued_responses: list[httpx.Response | Exception] = []
        self.models = [{"model": "qwen2.5:0.5b"}]

    def queue_json_body(
        self,
        response_body: str,
        *,
        model: str = "qwen2.5:0.5b",
        status_code: int = 200,
    ) -> None:
        self._queued_responses.append(
            httpx.Response(
                status_code,
                json={
                    "model": model,
                    "response": response_body,
                    "done": True,
                    "done_reason": "stop",
                },
            ),
        )

    def queue_response(self, response: httpx.Response | Exception) -> None:
        self._queued_responses.append(response)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()

        if path == "/api/tags" and method == "GET":
            return httpx.Response(200, json={"models": deepcopy(self.models)})

        if path == "/api/generate" and method == "POST":
            body = self._request_json(request)
            self.requests.append(body)
            if self._queued_responses:
                queued = self._queued_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued

            return httpx.Response(
                200,
                json={
                    "model": "qwen2.5:0.5b",
                    "response": '{"suggestions":[]}',
                    "done": True,
                    "done_reason": "stop",
                },
            )

        return httpx.Response(404, json={"detail": "not found"})

    @staticmethod
    def _request_json(request: httpx.Request) -> dict[str, object]:
        if not request.content:
            return {}
        return json.loads(request.content.decode("utf-8"))


@pytest.fixture
def database_api() -> FakeDatabaseApi:
    return FakeDatabaseApi()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_api_base_url="http://database.test")


@pytest.fixture
def ollama_api() -> FakeOllamaApi:
    return FakeOllamaApi()


@pytest.fixture
def client_factory():
    def _make(
        handler,
        *,
        settings_override: Settings | None = None,
        ollama_handler=None,
    ) -> Iterator[TestClient]:
        app = create_app(
            settings_override or Settings(database_api_base_url="http://database.test"),
            database_transport=httpx.MockTransport(handler),
            ollama_transport=(
                httpx.MockTransport(ollama_handler) if ollama_handler else None
            ),
        )
        return TestClient(app)

    return _make


@pytest.fixture
def client(
    client_factory,
    database_api: FakeDatabaseApi,
) -> Iterator[TestClient]:
    with client_factory(database_api.handle) as test_client:
        yield test_client
