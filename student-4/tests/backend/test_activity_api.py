from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

ACTIVITY_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
COUNTRY_ID = "11111111-1111-1111-1111-111111111111"
CITY_ID = "22222222-2222-2222-2222-222222222222"


def public_payload(name: str = "Harbour Kayak") -> dict:
    return {
        "name": name,
        "description": "Guided paddle on Sydney Harbour.",
        "price": "89.50",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
        "minimum_participants": 1,
        "booking_required": True,
        "is_active": True,
        "location_details": {
            "country": "Australia",
            "city": "Sydney",
            "street": "George Street",
            "street_number": 1,
        },
        "categories": ["ADVENTURE"],
        "availability_schedules": [
            {
                "recurring_weekly": True,
                "day_of_week": "MONDAY",
                "start_time": "09:00",
                "end_time": "12:00",
            }
        ],
    }


class FakeDatabase:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if path == "/internal/health":
            return httpx.Response(200, json={"status": "ok", "service": "db"})
        if path == "/internal/activity/categories":
            return httpx.Response(200, json={"categories": []})
        if path == "/internal/activity" and request.method == "POST":
            record = deepcopy(body)
            record["id"] = ACTIVITY_ID
            record["location_details"]["id"] = "33333333-3333-3333-3333-333333333333"
            record["availability_schedules"][0]["id"] = (
                "44444444-4444-4444-4444-444444444444"
            )
            self.records[ACTIVITY_ID] = record
            return httpx.Response(201, json=record)
        if path == "/internal/activity" and request.method == "QUERY":
            rows = [self._summary(record) for record in self.records.values()]
            return httpx.Response(
                200,
                json={
                    "activities": rows,
                    "total": len(rows),
                    "limit": body["limit"],
                    "offset": body["offset"],
                },
            )
        if path == f"/internal/activity/{ACTIVITY_ID}":
            if request.method == "GET":
                return self._get()
            if request.method == "PUT":
                record = deepcopy(body)
                record["id"] = ACTIVITY_ID
                record["location_details"]["id"] = (
                    "33333333-3333-3333-3333-333333333333"
                )
                record["availability_schedules"][0]["id"] = (
                    "44444444-4444-4444-4444-444444444444"
                )
                self.records[ACTIVITY_ID] = record
                return httpx.Response(200, json=record)
            if request.method == "DELETE":
                self.records.pop(ACTIVITY_ID, None)
                return httpx.Response(200, json={"id": ACTIVITY_ID, "deleted": True})
        return httpx.Response(404, json={"detail": "not found"})

    def _get(self) -> httpx.Response:
        record = self.records.get(ACTIVITY_ID)
        return (
            httpx.Response(200, json=record)
            if record
            else httpx.Response(404, json={"detail": "activity not found"})
        )

    @staticmethod
    def _summary(record: dict) -> dict:
        omitted = {"booking_notes", "accessibility_notes", "availability_schedules"}
        summary = {key: value for key, value in record.items() if key not in omitted}
        summary["location_details"] = {
            "country_id": record["location_details"]["country_id"],
            "city_id": record["location_details"]["city_id"],
        }
        return summary


def location_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/location/country":
        return httpx.Response(
            200,
            json={
                "countries": [{"id": COUNTRY_ID, "name": "australia"}],
                "total": 1,
            },
        )
    if request.url.path == "/location/city":
        return httpx.Response(
            200,
            json={
                "cities": [{"id": CITY_ID, "name": "sydney", "country_id": COUNTRY_ID}],
                "total": 1,
            },
        )
    return httpx.Response(404)


def make_client(database: FakeDatabase) -> TestClient:
    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(database.handle),
        location_transport=httpx.MockTransport(location_handler),
    )
    return TestClient(app)


def test_crud_translates_names_and_never_connects_to_database_directly() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        created = client.post("/activity", json=public_payload())
        assert created.status_code == 201
        assert created.json()["location_details"]["country"] == "australia"
        assert created.json()["location_details"]["city"] == "sydney"

        sent = database.calls[-1][2]
        assert sent["location_details"]["country_id"] == COUNTRY_ID
        assert sent["location_details"]["city_id"] == CITY_ID

        fetched = client.get(f"/activity/{ACTIVITY_ID}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Harbour Kayak"

        replaced = client.put(
            f"/activity/{ACTIVITY_ID}", json=public_payload("Sunset Harbour Kayak")
        )
        assert replaced.status_code == 200
        assert replaced.json()["name"] == "Sunset Harbour Kayak"

        deleted = client.delete(f"/activity/{ACTIVITY_ID}")
        assert deleted.status_code == 200
        assert deleted.json() == {"id": ACTIVITY_ID, "deleted": True}


def test_list_and_query_default_to_active_and_allow_management_override() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        client.post("/activity", json=public_payload())

        listed = client.get("/activity")
        assert listed.status_code == 200
        assert database.calls[-1][2]["is_active"] is True

        queried = client.request(
            "QUERY", "/activity", json={"include_inactive": True, "limit": 10}
        )
        assert queried.status_code == 200
        assert "is_active" not in database.calls[-1][2]
        assert queried.json()["activities"][0]["location_details"]["city"] == "sydney"


def test_unknown_write_location_is_a_400() -> None:
    database = FakeDatabase()
    payload = public_payload()
    payload["location_details"]["country"] = "Narnia"
    with make_client(database) as client:
        response = client.post("/activity", json=payload)
    assert response.status_code == 400
    assert database.records == {}


def test_uuid_is_validated_at_public_boundary() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        response = client.get("/activity/not-a-uuid")
    assert response.status_code == 400


def test_activity_identifier_is_a_uuid() -> None:
    assert UUID(ACTIVITY_ID)


def test_unresolved_location_ids_are_omitted_not_exposed_as_names() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        created = client.post("/activity", json=public_payload())
        assert created.status_code == 201
        database.records[ACTIVITY_ID]["location_details"]["country_id"] = (
            "99999999-9999-9999-9999-999999999999"
        )

        response = client.get(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 200
    assert "country" not in response.json()["location_details"]
    assert response.json()["location_details"]["city"] == "sydney"
