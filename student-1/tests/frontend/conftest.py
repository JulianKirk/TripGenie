from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from frontend_service.app import create_app
from frontend_service.config import Settings

TRIP_STATUS_ISSUE = "must be one of: draft, planned, active, completed, cancelled"
ITEM_CATEGORY_ISSUE = (
    "must be one of: accommodation, transport, activity, meal, note, other"
)


def create_trip_form_data(**overrides: str) -> dict[str, str]:
    payload = {
        "id": "",
        "name": "Canberra Planning Sprint",
        "destination": "Canberra",
        "start_date": "2027-05-01",
        "end_date": "2027-05-04",
        "traveller_count": "2",
        "status": "planned",
        "notes": "Need a mix of museums and cafes.",
    }
    payload.update(overrides)
    return payload


def create_item_form_data(**overrides: str) -> dict[str, str]:
    payload = {
        "id": "",
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


class FakeBackendApi:
    def __init__(self) -> None:
        self._trip_counter = 0
        self._item_counter = 0
        self.ai_requests: list[dict[str, object]] = []
        self.ai_responses: list[httpx.Response] = []
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
            "service": "student-1-backend",
            "dependencies": {
                "database": {
                    "status": "ok",
                    "service": "student-1-database",
                    "detail": "Database API responded successfully.",
                    "code": None,
                },
                "ai_mode": {
                    "status": "not_configured",
                    "service": "ai-mode",
                    "detail": (
                        "Shared AI-Mode is disabled because no runtime base URL is "
                        "configured."
                    ),
                    "code": None,
                },
            },
        }
        self.ready_payload = deepcopy(self.health_payload)
        self.ready_status_code = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        path_parts = request.url.path.strip("/").split("/")
        method = request.method.upper()

        if path_parts == ["health"] and method == "GET":
            return data_response(200, deepcopy(self.health_payload))

        if path_parts == ["ready"] and method == "GET":
            return data_response(self.ready_status_code, deepcopy(self.ready_payload))

        if path_parts == ["api", "trips"]:
            if method == "GET":
                return data_response(200, self._list_trips())
            if method == "POST":
                return self._create_trip(request)

        if len(path_parts) == 3 and path_parts[:2] == ["api", "trips"]:
            trip_id = path_parts[2]
            if method == "GET":
                return self._get_trip(trip_id)
            if method == "PATCH":
                return self._update_trip(trip_id, request)
            if method == "DELETE":
                return self._delete_trip(trip_id)

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["api", "trips"]
            and path_parts[3] == "itinerary-items"
            and method == "POST"
        ):
            return self._create_item(path_parts[2], request)

        if (
            len(path_parts) == 4
            and path_parts[:2] == ["api", "trips"]
            and path_parts[3] == "ai-suggestions"
            and method == "POST"
        ):
            return self._create_ai_suggestions(path_parts[2], request)

        if len(path_parts) == 3 and path_parts[:2] == ["api", "itinerary-items"]:
            item_id = path_parts[2]
            if method == "GET":
                return self._get_item(item_id)
            if method == "PATCH":
                return self._update_item(item_id, request)
            if method == "DELETE":
                return self._delete_item(item_id)

        return httpx.Response(404, json={"detail": "not found"})

    def _list_trips(self) -> list[dict[str, object]]:
        return sorted(
            (self._trip_summary(trip) for trip in self.trips.values()),
            key=lambda trip: (
                str(trip["start_date"]),
                str(trip["name"]).lower(),
                str(trip["id"]),
            ),
        )

    def _create_trip(self, request: httpx.Request) -> httpx.Response:
        payload = self._request_json(request)
        validation_error_response = self._validate_trip_payload(payload)
        if validation_error_response is not None:
            return validation_error_response

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
            "traveller_count": int(payload["traveller_count"]),
            "status": payload["status"],
            "notes": payload.get("notes") or None,
        }
        self.trips[trip_id] = record
        return data_response(201, self._trip_detail(trip_id))

    def _get_trip(self, trip_id: str) -> httpx.Response:
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        return data_response(200, self._trip_detail(trip_id))

    def _update_trip(self, trip_id: str, request: httpx.Request) -> httpx.Response:
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        payload = self._request_json(request)
        merged = deepcopy(self.trips[trip_id])
        merged.update(payload)
        validation_error_response = self._validate_trip_payload(merged)
        if validation_error_response is not None:
            return validation_error_response

        self.trips[trip_id] = {
            **self.trips[trip_id],
            "name": merged["name"],
            "destination": merged["destination"],
            "start_date": merged["start_date"],
            "end_date": merged["end_date"],
            "traveller_count": int(merged["traveller_count"]),
            "status": merged["status"],
            "notes": merged.get("notes") or None,
        }
        return data_response(200, self._trip_detail(trip_id))

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

    def _create_item(self, trip_id: str, request: httpx.Request) -> httpx.Response:
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        payload = self._request_json(request)
        validation_error_response = self._validate_item_payload(trip_id, payload)
        if validation_error_response is not None:
            return validation_error_response

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
            "start_time": payload.get("start_time") or None,
            "end_time": payload.get("end_time") or None,
            "title": payload["title"],
            "location": payload.get("location") or None,
            "description": payload.get("description") or None,
            "category": payload["category"],
            "notes": payload.get("notes") or None,
        }
        self.items[item_id] = record
        return data_response(201, deepcopy(record))

    def _create_ai_suggestions(
        self,
        trip_id: str,
        request: httpx.Request,
    ) -> httpx.Response:
        if trip_id not in self.trips:
            return error_response(
                404,
                "NOT_FOUND",
                f"Trip '{trip_id}' was not found.",
                [{"field": "id", "issue": "resource does not exist"}],
            )

        payload = self._request_json(request)
        self.ai_requests.append(deepcopy(payload))
        if self.ai_responses:
            return self.ai_responses.pop(0)

        details: list[dict[str, str]] = []
        requested_date = str(payload.get("requested_date", "")).strip()
        goal = str(payload.get("goal", "")).strip()
        if not requested_date:
            details.append({"field": "requested_date", "issue": "must not be blank"})
        elif not self._is_iso_date(requested_date):
            details.append(
                {
                    "field": "requested_date",
                    "issue": "must be a valid ISO date in YYYY-MM-DD format",
                },
            )
        else:
            trip = self.trips[trip_id]
            if requested_date < str(trip["start_date"]) or requested_date > str(
                trip["end_date"]
            ):
                details.append(
                    {
                        "field": "requested_date",
                        "issue": (
                            f"must fall between {trip['start_date']} and "
                            f"{trip['end_date']}"
                        ),
                    },
                )
        if not goal:
            details.append({"field": "goal", "issue": "must not be blank"})

        if details:
            return error_response(
                422,
                "VALIDATION_ERROR",
                "One or more fields failed validation.",
                details,
            )

        suggestions = [
            {
                "date": requested_date,
                "start_time": "12:30",
                "end_time": "14:00",
                "title": "Waterside Lunch",
                "location": "Barangaroo",
                "description": "Relaxed lunch with harbour views.",
                "category": "meal",
                "notes": "Keep it flexible.",
                "rationale": "Creates a calm midday stop.",
                "persisted": False,
                "approval_required": True,
            },
            {
                "date": requested_date,
                "start_time": "14:30",
                "end_time": "16:00",
                "title": "Reserve Walk",
                "location": "Barangaroo Reserve",
                "description": "Gentle foreshore walk with rest stops.",
                "category": "activity",
                "notes": "Pause for photos if the weather is good.",
                "rationale": "Adds a low-energy outdoor option.",
                "persisted": False,
                "approval_required": True,
            },
        ]
        return data_response(
            200,
            {
                "trip_id": trip_id,
                "requested_date": requested_date,
                "model": "qwen2.5:0.5b",
                "prompt_asset": "runtime_ai_suggestions_v1.md",
                "run_id": "ai_demo_run_01",
                "correlation_id": "ai_demo_run_01",
                "attempt_count": 1,
                "persisted": False,
                "approval_required": True,
                "suggestions": suggestions,
            },
        )

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

        merged = deepcopy(record)
        merged.update(self._request_json(request))
        validation_error_response = self._validate_item_payload(
            str(record["trip_id"]), merged
        )
        if validation_error_response is not None:
            return validation_error_response

        merged["start_time"] = merged.get("start_time") or None
        merged["end_time"] = merged.get("end_time") or None
        merged["location"] = merged.get("location") or None
        merged["description"] = merged.get("description") or None
        merged["notes"] = merged.get("notes") or None
        self.items[item_id] = merged
        return data_response(200, deepcopy(merged))

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

    def _validate_trip_payload(
        self, payload: dict[str, object]
    ) -> httpx.Response | None:
        details: list[dict[str, str]] = []
        required_fields = (
            "name",
            "destination",
            "start_date",
            "end_date",
            "traveller_count",
            "status",
        )
        for field_name in required_fields:
            if str(payload.get(field_name, "")).strip() == "":
                details.append({"field": field_name, "issue": "must not be blank"})

        start_date = str(payload.get("start_date", "")).strip()
        end_date = str(payload.get("end_date", "")).strip()
        if (
            start_date
            and end_date
            and self._is_iso_date(start_date)
            and self._is_iso_date(end_date)
        ):
            if start_date > end_date:
                details.append(
                    {"field": "start_date", "issue": "must be on or before end_date"}
                )

        try:
            traveller_count = int(str(payload.get("traveller_count", "")).strip())
            if traveller_count < 1:
                details.append(
                    {
                        "field": "traveller_count",
                        "issue": "Input should be greater than or equal to 1",
                    }
                )
        except ValueError:
            details.append(
                {"field": "traveller_count", "issue": "Input should be a valid integer"}
            )

        status_value = str(payload.get("status", "")).strip()
        if status_value and status_value not in {
            "draft",
            "planned",
            "active",
            "completed",
            "cancelled",
        }:
            details.append(
                {
                    "field": "status",
                    "issue": TRIP_STATUS_ISSUE,
                },
            )

        if details:
            return error_response(
                422,
                "VALIDATION_ERROR",
                "One or more fields failed validation.",
                details,
            )
        return None

    def _validate_item_payload(
        self,
        trip_id: str,
        payload: dict[str, object],
    ) -> httpx.Response | None:
        details: list[dict[str, str]] = []
        required_fields = ("date", "title", "category")
        for field_name in required_fields:
            if str(payload.get(field_name, "")).strip() == "":
                details.append({"field": field_name, "issue": "must not be blank"})

        trip = self.trips[trip_id]
        item_date = str(payload.get("date", "")).strip()
        if item_date:
            if not self._is_iso_date(item_date):
                details.append(
                    {
                        "field": "date",
                        "issue": "must be a valid ISO date in YYYY-MM-DD format",
                    },
                )
            elif item_date < str(trip["start_date"]) or item_date > str(
                trip["end_date"]
            ):
                details.append(
                    {
                        "field": "date",
                        "issue": (
                            f"must fall between {trip['start_date']} and "
                            f"{trip['end_date']}"
                        ),
                    },
                )

        start_time = str(payload.get("start_time", "") or "").strip()
        end_time = str(payload.get("end_time", "") or "").strip()
        if start_time and not self._is_iso_time(start_time):
            details.append(
                {"field": "start_time", "issue": "must be a valid HH:MM time"}
            )
        if end_time and not self._is_iso_time(end_time):
            details.append({"field": "end_time", "issue": "must be a valid HH:MM time"})
        if start_time and end_time and start_time >= end_time:
            details.append(
                {
                    "field": "start_time",
                    "issue": "must be earlier than end_time when both are provided",
                },
            )

        category_value = str(payload.get("category", "")).strip()
        if category_value and category_value not in {
            "accommodation",
            "transport",
            "activity",
            "meal",
            "note",
            "other",
        }:
            details.append(
                {
                    "field": "category",
                    "issue": ITEM_CATEGORY_ISSUE,
                },
            )

        if details:
            return error_response(
                422,
                "VALIDATION_ERROR",
                "One or more fields failed validation.",
                details,
            )
        return None

    def _trip_summary(self, trip: dict[str, object]) -> dict[str, object]:
        return {
            "id": trip["id"],
            "name": trip["name"],
            "destination": trip["destination"],
            "start_date": trip["start_date"],
            "end_date": trip["end_date"],
            "traveller_count": trip["traveller_count"],
            "status": trip["status"],
            "notes": trip["notes"],
        }

    def _trip_detail(self, trip_id: str) -> dict[str, object]:
        trip = deepcopy(self.trips[trip_id])
        days: list[dict[str, object]] = []
        current_day = date.fromisoformat(str(trip["start_date"]))
        final_day = date.fromisoformat(str(trip["end_date"]))
        while current_day <= final_day:
            iso_day = current_day.isoformat()
            day_items = [
                deepcopy(item)
                for item in self.items.values()
                if item["trip_id"] == trip_id and item["date"] == iso_day
            ]
            day_items.sort(
                key=lambda item: (
                    str(item["date"]),
                    1 if item["start_time"] is None else 0,
                    str(item["start_time"] or ""),
                    str(item["title"]).lower(),
                    str(item["id"]),
                ),
            )
            days.append({"date": iso_day, "items": day_items})
            current_day += timedelta(days=1)

        trip["days"] = days
        return trip

    def _next_trip_id(self) -> str:
        self._trip_counter += 1
        return f"trip_generated_{self._trip_counter:02d}"

    def _next_item_id(self) -> str:
        self._item_counter += 1
        return f"item_generated_{self._item_counter:02d}"

    @staticmethod
    def _request_json(request: httpx.Request) -> dict[str, object]:
        body = request.content.decode("utf-8")
        return json.loads(body) if body else {}

    @staticmethod
    def _is_iso_date(value: str) -> bool:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_iso_time(value: str) -> bool:
        return re.fullmatch(r"\d{2}:\d{2}", value) is not None


@pytest.fixture
def backend_api() -> FakeBackendApi:
    return FakeBackendApi()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def client_factory(backend_api: FakeBackendApi):
    def factory(handler=None) -> TestClient:
        app = create_app(
            Settings(
                backend_base_url="http://backend.test",
                backend_api_prefix="/api",
                backend_timeout_seconds=1,
                service_name="student-1-frontend",
            ),
            transport=httpx.MockTransport(handler or backend_api.handle),
        )
        return TestClient(app)

    return factory


@pytest.fixture
def async_client_factory(backend_api: FakeBackendApi):
    @asynccontextmanager
    async def factory(handler=None) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app(
            Settings(
                backend_base_url="http://backend.test",
                backend_api_prefix="/api",
                backend_timeout_seconds=1,
                service_name="student-1-frontend",
            ),
            transport=httpx.MockTransport(handler or backend_api.handle),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                follow_redirects=False,
            ) as async_client:
                yield async_client

    return factory


@pytest.fixture
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client
