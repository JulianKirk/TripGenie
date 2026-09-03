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
        # (trip_id, accommodation_id) -> the stored row, the associative
        # entity as the database service keeps it.
        self.trip_accommodations: dict[tuple[str, str], dict[str, object]] = {}
        self.trip_activities: dict[tuple[str, str], dict[str, object]] = {}
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

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["internal", "trips"]
            and path_parts[3] == "accommodations"
            and method == "GET"
        ):
            return self._list_trip_accommodations(path_parts[2])

        if (
            len(path_parts) == 5
            and path_parts[:2] == ["internal", "trips"]
            and path_parts[3] == "accommodations"
        ):
            trip_id, accommodation_id = path_parts[2], path_parts[4]
            if method == "PUT":
                return self._add_trip_accommodation(trip_id, accommodation_id, request)
            if method == "DELETE":
                return self._remove_trip_accommodation(trip_id, accommodation_id)

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["internal", "accommodations"]
            and path_parts[3] == "trips"
            and method == "GET"
        ):
            return self._list_trips_for_accommodation(path_parts[2])

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["internal", "trips"]
            and path_parts[3] == "activities"
            and method == "GET"
        ):
            return self._list_trip_activities(path_parts[2])

        if (
            len(path_parts) == 5
            and path_parts[:2] == ["internal", "trips"]
            and path_parts[3] == "activities"
        ):
            trip_id, activity_id = path_parts[2], path_parts[4]
            if method == "PUT":
                return self._add_trip_activity(trip_id, activity_id, request)
            if method == "DELETE":
                return self._remove_trip_activity(trip_id, activity_id)

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["internal", "activities"]
            and path_parts[3] == "trips"
            and method == "GET"
        ):
            return self._list_trips_for_activity(path_parts[2])

        if len(path_parts) == 3 and path_parts[:2] == ["internal", "itinerary-items"]:
            item_id = path_parts[2]
            if method == "GET":
                return self._get_item(item_id)
            if method == "PATCH":
                return self._update_item(item_id, request)
            if method == "DELETE":
                return self._delete_item(item_id)

        return httpx.Response(404, json={"detail": "not found"})

    def _list_trip_accommodations(self, trip_id: str) -> httpx.Response:
        if trip_id not in self.trips:
            return self._trip_not_found(trip_id)

        return data_response(200, self._trip_accommodation_records(trip_id))

    def _add_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
        request: httpx.Request,
    ) -> httpx.Response:
        if trip_id not in self.trips:
            return self._trip_not_found(trip_id)

        key = (trip_id, accommodation_id)
        # Replaces the pin, like the real service: PUT moves the stay rather
        # than keeping whatever the first call recorded.
        body = self._request_json(request)
        self.trip_accommodations[key] = {
            "trip_id": trip_id,
            "accommodation_id": accommodation_id,
            "date": str(body["date"]),
            "check_in_time": body.get("check_in_time"),
            "check_out": body.get("check_out"),
            "check_out_time": body.get("check_out_time"),
        }
        return data_response(200, self.trip_accommodations[key])

    def _remove_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
    ) -> httpx.Response:
        if trip_id not in self.trips:
            return self._trip_not_found(trip_id)

        if self.trip_accommodations.pop((trip_id, accommodation_id), None) is None:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip accommodation '{accommodation_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        return data_response(200, {"id": accommodation_id, "deleted": True})

    def _list_trips_for_accommodation(self, accommodation_id: str) -> httpx.Response:
        trip_ids = {
            trip_id
            for trip_id, pinned_id in self.trip_accommodations
            if pinned_id == accommodation_id
        }
        return data_response(
            200,
            [trip for trip in self._list_trips({}) if trip["id"] in trip_ids],
        )

    def _trip_accommodation_records(self, trip_id: str) -> list[dict[str, object]]:
        return sorted(
            (
                dict(record)
                for (pinned_trip, accommodation_id), record in (
                    self.trip_accommodations.items()
                )
                if pinned_trip == trip_id
            ),
            key=lambda record: (record["date"], record["accommodation_id"]),
        )

    def _list_trip_activities(self, trip_id: str) -> httpx.Response:
        if trip_id not in self.trips:
            return self._trip_not_found(trip_id)
        records = sorted(
            (
                deepcopy(record)
                for (pinned_trip, _), record in self.trip_activities.items()
                if pinned_trip == trip_id
            ),
            key=lambda record: (record["date"], record["activity_id"]),
        )
        return data_response(200, records)

    def _add_trip_activity(
        self,
        trip_id: str,
        activity_id: str,
        request: httpx.Request,
    ) -> httpx.Response:
        if trip_id not in self.trips:
            return self._trip_not_found(trip_id)
        body = self._request_json(request)
        record = {
            "trip_id": trip_id,
            "activity_id": activity_id,
            "date": str(body["date"]),
            "start_time": body.get("start_time"),
        }
        self.trip_activities[(trip_id, activity_id)] = record
        return data_response(200, deepcopy(record))

    def _remove_trip_activity(self, trip_id: str, activity_id: str) -> httpx.Response:
        if trip_id not in self.trips:
            return self._trip_not_found(trip_id)
        if self.trip_activities.pop((trip_id, activity_id), None) is None:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip activity '{activity_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )
        return data_response(200, {"id": activity_id, "deleted": True})

    def _list_trips_for_activity(self, activity_id: str) -> httpx.Response:
        trip_ids = {
            trip_id
            for trip_id, pinned_id in self.trip_activities
            if pinned_id == activity_id
        }
        return data_response(
            200,
            [trip for trip in self._list_trips({}) if trip["id"] in trip_ids],
        )

    def _trip_not_found(self, trip_id: str) -> httpx.Response:
        return error_response(
            404,
            "NOT_FOUND",
            f"Trip '{trip_id}' was not found.",
            [{"field": "id", "issue": "resource does not exist"}],
        )

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
        self.trip_accommodations = {
            key: value
            for key, value in self.trip_accommodations.items()
            if key[0] != trip_id
        }
        self.trip_activities = {
            key: value
            for key, value in self.trip_activities.items()
            if key[0] != trip_id
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


class FakeAiModeApi:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.health_requests = 0
        self.ready_requests = 0
        self._queued_generate_responses: list[httpx.Response | Exception] = []
        self._queued_health_responses: list[httpx.Response | Exception] = []
        self._queued_ready_responses: list[httpx.Response | Exception] = []
        self.health_payload = {
            "status": "ok",
            "service": "ai-mode",
            "dependencies": {
                "ollama": {
                    "status": "ok",
                    "service": "ollama",
                    "detail": (
                        "Ollama responded successfully and the configured model is "
                        "available."
                    ),
                    "code": None,
                }
            },
        }
        self.ready_payload = deepcopy(self.health_payload)
        self._response_counter = 0

    def queue_json_body(
        self,
        response_body: str,
        *,
        model: str = "qwen2.5:0.5b",
        status_code: int = 200,
    ) -> None:
        self._response_counter += 1
        self._queued_generate_responses.append(
            data_response(
                status_code,
                {
                    "run_id": f"aimode_run_{self._response_counter:02d}",
                    "correlation_id": f"aimode_corr_{self._response_counter:02d}",
                    "model": model,
                    "provider": "ollama",
                    "response": response_body,
                    "done": True,
                },
            )
        )

    def queue_response(self, response: httpx.Response | Exception) -> None:
        self._queued_generate_responses.append(response)

    def queue_health_response(self, response: httpx.Response | Exception) -> None:
        self._queued_health_responses.append(response)

    def queue_ready_response(self, response: httpx.Response | Exception) -> None:
        self._queued_ready_responses.append(response)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()

        if path == "/health" and method == "GET":
            self.health_requests += 1
            if self._queued_health_responses:
                queued = self._queued_health_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued
            return data_response(200, deepcopy(self.health_payload))

        if path == "/ready" and method == "GET":
            self.ready_requests += 1
            if self._queued_ready_responses:
                queued = self._queued_ready_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued
            return data_response(200, deepcopy(self.ready_payload))

        if path == "/generate" and method == "POST":
            body = self._request_json(request)
            self.requests.append(body)
            if self._queued_generate_responses:
                queued = self._queued_generate_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued

            self._response_counter += 1
            return data_response(
                200,
                {
                    "run_id": f"aimode_run_{self._response_counter:02d}",
                    "correlation_id": body.get("correlation_id", ""),
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": '{"suggestions":[]}',
                    "done": True,
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


class FakeAccommodationApi:
    """Student 2's public API, as much of it as this service reads.

    Answers 404 for anything it has not been given, which is also what the real
    service does for an accommodation it does not know -- and is the shape this
    service has to survive, since a name it cannot fetch must not cost the page.
    """

    def __init__(self, records: dict[str, dict] | None = None) -> None:
        self.records = records or {}
        self.calls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        accommodation_id = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(accommodation_id)
        record = self.records.get(accommodation_id)
        if record is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=record)


@pytest.fixture
def ai_mode_api() -> FakeAiModeApi:
    return FakeAiModeApi()


@pytest.fixture
def accommodation_api() -> FakeAccommodationApi:
    return FakeAccommodationApi()


class FakeActivityApi:
    def __init__(self, records: dict[str, dict] | None = None) -> None:
        self.records = records or {}
        self.calls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        activity_id = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(activity_id)
        record = self.records.get(activity_id)
        if record is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=record)


@pytest.fixture
def activity_api() -> FakeActivityApi:
    return FakeActivityApi()


@pytest.fixture
def client_factory(
    accommodation_api: FakeAccommodationApi,
    activity_api: FakeActivityApi,
):
    def _make(
        handler,
        *,
        settings_override: Settings | None = None,
        ai_mode_handler=None,
    ) -> Iterator[TestClient]:
        app = create_app(
            settings_override or Settings(database_api_base_url="http://database.test"),
            database_transport=httpx.MockTransport(handler),
            ai_mode_transport=(
                httpx.MockTransport(ai_mode_handler) if ai_mode_handler else None
            ),
            accommodation_transport=httpx.MockTransport(accommodation_api.handle),
            activity_transport=httpx.MockTransport(activity_api.handle),
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
