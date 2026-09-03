from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

from tests.backend.test_activity_api import ACTIVITY_ID, FakeDatabase, location_handler

SYDNEY = "trip_2027_sydney_getaway"
TOKYO = "trip_2027_tokyo_city_break"


class FakeItinerary:
    def __init__(self) -> None:
        self.trips = [
            {
                "id": SYDNEY,
                "name": "Sydney Getaway",
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
            },
            {
                "id": TOKYO,
                "name": "Tokyo Break",
                "start_date": "2027-05-10",
                "end_date": "2027-05-12",
            },
        ]
        self.rows: dict[tuple[str, str], dict] = {}

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
                body = json.loads(request.content)
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
