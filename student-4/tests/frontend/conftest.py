from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast

import httpx
import pytest
from student4_frontend_service.client import BackendClient
from student4_frontend_service.config import Settings

ACTIVITY_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
SCHEDULE_ID = "44444444-4444-4444-4444-444444444444"
TRIP_ID = "trip_2027_sydney_getaway"

SUMMARY: dict[str, Any] = {
    "id": ACTIVITY_ID,
    "name": "Sydney Harbour guided walk",
    "description": "A guided walk around the harbour foreshore.",
    "price": "45.00",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 120,
    "minimum_age": 8,
    "minimum_participants": 1,
    "maximum_participants": 12,
    "booking_required": True,
    "wheelchair_accessible": False,
    "step_free_access": False,
    "accessible_toilet": True,
    "is_active": True,
    "location_details": {"country": "australia", "city": "sydney"},
    "categories": ["OUTDOOR", "TOUR"],
}

DETAIL: dict[str, Any] = {
    **SUMMARY,
    "booking_notes": "Arrange at least 24 hours ahead.",
    "accessibility_notes": "Some sections contain steep paths.",
    "location_details": {
        "country": "australia",
        "city": "sydney",
        "street": "circular quay",
    },
    "availability_schedules": [
        {
            "id": SCHEDULE_ID,
            "recurring_weekly": True,
            "day_of_week": "SATURDAY",
            "start_time": "09:00",
            "end_time": "11:00",
        }
    ],
}

CATEGORIES = {
    "categories": [
        {
            "code": "OUTDOOR",
            "label": "Outdoor",
            "description": "Activities primarily undertaken outdoors",
            "display_order": 60,
        },
        {
            "code": "TOUR",
            "label": "Tour",
            "description": None,
            "display_order": 80,
        },
    ]
}

ITINERARIES = {
    "itineraries": [
        {
            "itinerary_id": TRIP_ID,
            "name": "Sydney Getaway",
            "selected": False,
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
        }
    ]
}


class FakeBackend:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.overrides: dict[tuple[str, str], httpx.Response | Exception] = {}

    @property
    def last_request(self) -> httpx.Request:
        return self.requests[-1]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        override = self.overrides.get((request.method, request.url.path))
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override

        return self._default_response(request)

    @staticmethod
    def _default_response(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "service": "student-4-backend",
                    "database": "ok",
                    "location": "ok",
                },
            )
        if path == "/activity/categories":
            return httpx.Response(200, json=deepcopy(CATEGORIES))
        if path == "/activity" and request.method in {"GET", "QUERY"}:
            return httpx.Response(
                200,
                json={
                    "activities": [deepcopy(SUMMARY)],
                    "total": 1,
                    "limit": 20,
                    "offset": 0,
                },
            )
        if path == "/activity" and request.method == "POST":
            return httpx.Response(201, json=deepcopy(DETAIL))
        if path == f"/activity/{ACTIVITY_ID}" and request.method in {"GET", "PUT"}:
            return httpx.Response(200, json=deepcopy(DETAIL))
        if path == f"/activity/{ACTIVITY_ID}" and request.method == "DELETE":
            return httpx.Response(200, json={"id": ACTIVITY_ID, "deleted": True})
        if path == f"/activity/{ACTIVITY_ID}/itineraries":
            return httpx.Response(200, json=deepcopy(ITINERARIES))
        if path == f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}":
            result = deepcopy(ITINERARIES)
            selected = request.method == "PUT"
            result["itineraries"][0]["selected"] = selected
            if selected and request.content:
                result["itineraries"][0].update(json.loads(request.content))
            return httpx.Response(200, json=result)
        return httpx.Response(404, json={"detail": "not found"})

    def json_body(self) -> dict[str, Any]:
        return cast("dict[str, Any]", json.loads(self.last_request.content))


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def backend_client(backend: FakeBackend) -> BackendClient:
    return BackendClient(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
