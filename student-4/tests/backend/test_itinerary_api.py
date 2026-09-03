from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

from tests.backend.test_activity_api import ACTIVITY_ID, FakeDatabase, location_handler

SYDNEY = "trip_2027_sydney_getaway"
TOKYO = "trip_2027_tokyo_city_break"


class FakeItinerary:
    def __init__(self) -> None:
        self.trips: list[dict[str, Any]] = [
            {
                "id": SYDNEY,
                "name": "Sydney Getaway",
                "destination": "Sydney",
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
                "traveller_count": 2,
                "status": "planned",
                "notes": None,
            },
            {
                "id": TOKYO,
                "name": "Tokyo Break",
                "destination": "Tokyo",
                "start_date": "2027-05-10",
                "end_date": "2027-05-12",
                "traveller_count": 2,
                "status": "planned",
                "notes": None,
            },
        ]
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/trips":
            return httpx.Response(200, json={"data": self.trips})
        if path == f"/api/activities/{ACTIVITY_ID}/trips":
            held = {
                trip_id
                for trip_id, activity_id in self.rows
                if activity_id == ACTIVITY_ID
            }
            return httpx.Response(
                200,
                json={"data": [trip for trip in self.trips if trip["id"] in held]},
            )
        for trip in (SYDNEY, TOKYO):
            collection = f"/api/trips/{trip}/activities"
            member = f"{collection}/{ACTIVITY_ID}"
            if path == collection:
                rows = [
                    row for (trip_id, _), row in self.rows.items() if trip_id == trip
                ]
                return httpx.Response(200, json={"data": rows})
            if path == member and request.method == "PUT":
                body = cast("dict[str, Any]", json.loads(request.content))
                row = {"trip_id": trip, "activity_id": ACTIVITY_ID, **body}
                self.rows[(trip, ACTIVITY_ID)] = row
                return httpx.Response(200, json={"data": row})
            if path == member and request.method == "DELETE":
                self.rows.pop((trip, ACTIVITY_ID), None)
                return httpx.Response(
                    200, json={"data": {"id": ACTIVITY_ID, "deleted": True}}
                )
        return httpx.Response(404, json={"detail": "not found"})


def test_activity_itinerary_picker_adds_schedules_and_removes() -> None:
    itinerary = FakeItinerary()
    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(itinerary.handle),
    )
    with TestClient(app) as client:
        initial = client.get(f"/activity/{ACTIVITY_ID}/itineraries")
        assert initial.status_code == 200
        assert [row["selected"] for row in initial.json()["itineraries"]] == [
            False,
            False,
        ]

        added = client.put(
            f"/activity/{ACTIVITY_ID}/itineraries/{SYDNEY}",
            json={"date": "2027-04-02", "start_time": "09:30"},
        )
        selected = added.json()["itineraries"][0]
        assert selected["selected"] is True
        assert selected["date"] == "2027-04-02"
        assert selected["start_time"] == "09:30"

        removed = client.delete(f"/activity/{ACTIVITY_ID}/itineraries/{SYDNEY}")
        assert removed.status_code == 200
        assert removed.json()["itineraries"][0]["selected"] is False


def test_itinerary_start_time_rejects_seconds_instead_of_truncating() -> None:
    itinerary = FakeItinerary()
    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(itinerary.handle),
    )
    with TestClient(app) as client:
        response = client.put(
            f"/activity/{ACTIVITY_ID}/itineraries/{SYDNEY}",
            json={"date": "2027-04-02", "start_time": "09:30:59"},
        )

    assert response.status_code == 400
    assert itinerary.rows == {}


def test_malformed_itinerary_dependency_response_is_a_502() -> None:
    def malformed_itinerary(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/trips":
            return httpx.Response(200, json={"data": [{"id": SYDNEY}]})
        if request.url.path == f"/api/activities/{ACTIVITY_ID}/trips":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404, json={"detail": "not found"})

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(malformed_itinerary),
    )
    with TestClient(app) as client:
        response = client.get(f"/activity/{ACTIVITY_ID}/itineraries")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from itinerary service"}


@pytest.mark.parametrize("upstream_status", [400, 404, 409, 422])
def test_student_1_error_envelope_is_normalised_to_public_detail(
    upstream_status: int,
) -> None:
    itinerary = FakeItinerary()

    def rejecting_itinerary(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(
                upstream_status,
                json={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Activity date must fall inside the trip.",
                        "details": [{"field": "date", "issue": "out of range"}],
                    }
                },
            )
        return itinerary.handle(request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(rejecting_itinerary),
    )
    with TestClient(app) as client:
        response = client.put(
            f"/activity/{ACTIVITY_ID}/itineraries/{SYDNEY}",
            json={"date": "2027-04-09"},
        )

    assert response.status_code == upstream_status
    assert response.json() == {"detail": "Activity date must fall inside the trip."}


def test_malformed_student_1_error_envelope_is_a_502() -> None:
    itinerary = FakeItinerary()

    def malformed_error(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(422, json={"error": {"message": ""}})
        return itinerary.handle(request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(malformed_error),
    )
    with TestClient(app) as client:
        response = client.put(
            f"/activity/{ACTIVITY_ID}/itineraries/{SYDNEY}",
            json={"date": "2027-04-02"},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from itinerary service"}


def test_itinerary_delete_contract_rejects_string_boolean() -> None:
    itinerary = FakeItinerary()

    def coercive_delete(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(
                200, json={"data": {"id": ACTIVITY_ID, "deleted": "false"}}
            )
        return itinerary.handle(request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(coercive_delete),
    )
    with TestClient(app) as client:
        response = client.delete(f"/activity/{ACTIVITY_ID}/itineraries/{SYDNEY}")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from itinerary service"}
