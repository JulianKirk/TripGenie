from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

ACTIVITY_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
COUNTRY_ID = "11111111-1111-1111-1111-111111111111"
CITY_ID = "22222222-2222-2222-2222-222222222222"


JsonObject = dict[str, Any]


def public_payload(name: str = "Harbour Kayak") -> JsonObject:
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
        self.records: dict[str, JsonObject] = {}
        self.calls: list[tuple[str, str, JsonObject | None]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = (
            cast("JsonObject", json.loads(request.content)) if request.content else None
        )
        self.calls.append((request.method, path, body))
        if path == "/internal/health":
            return httpx.Response(200, json={"status": "ok", "service": "db"})
        if path == "/internal/activity/categories":
            return httpx.Response(200, json={"categories": []})
        if path == "/internal/activity" and request.method == "POST":
            assert body is not None
            record = deepcopy(body)
            record["id"] = ACTIVITY_ID
            record["location_details"]["id"] = "33333333-3333-3333-3333-333333333333"
            record["availability_schedules"][0]["id"] = (
                "44444444-4444-4444-4444-444444444444"
            )
            self.records[ACTIVITY_ID] = record
            return httpx.Response(201, json=record)
        if path == "/internal/activity" and request.method == "QUERY":
            assert body is not None
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
                assert body is not None
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
    def _summary(record: JsonObject) -> JsonObject:
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
        assert sent is not None
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
        listed_query = database.calls[-1][2]
        assert listed_query is not None
        assert listed_query["is_active"] is True

        queried = client.request(
            "QUERY", "/activity", json={"include_inactive": True, "limit": 10}
        )
        assert queried.status_code == 200
        management_query = database.calls[-1][2]
        assert management_query is not None
        assert "is_active" not in management_query
        assert queried.json()["activities"][0]["location_details"]["city"] == "sydney"


def test_street_only_query_preserves_the_location_filter() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        response = client.request(
            "QUERY", "/activity", json={"location": {"street": "George"}}
        )

    assert response.status_code == 200
    sent = database.calls[-1][2]
    assert sent is not None
    assert sent["location_details"] == {"street": "George"}


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


def test_malformed_location_dependency_response_is_a_502() -> None:
    database = FakeDatabase()
    country_calls = 0

    def malformed_after_first_load(request: httpx.Request) -> httpx.Response:
        nonlocal country_calls
        if request.url.path == "/location/country":
            country_calls += 1
            if country_calls > 1:
                return httpx.Response(
                    200, json={"countries": [{"name": "australia"}], "total": 1}
                )
        return location_handler(request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(database.handle),
        location_transport=httpx.MockTransport(malformed_after_first_load),
    )
    with TestClient(app) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        database.records[ACTIVITY_ID]["location_details"]["country_id"] = (
            "99999999-9999-9999-9999-999999999999"
        )
        response = client.get(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from location service"}


def test_database_activity_contract_rejects_invalid_aggregate() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        record = database.records[ACTIVITY_ID]
        record["categories"] = ["INVENTED"]
        record["minimum_age"] = 20
        record["maximum_age"] = 10
        record["availability_schedules"] = []
        response = client.get(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from database service"}


def test_database_category_contract_rejects_unknown_codes() -> None:
    database = FakeDatabase()

    def malformed_categories(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/activity/categories":
            return httpx.Response(
                200,
                json={
                    "categories": [
                        {
                            "code": "INVENTED",
                            "label": "Invented",
                            "description": None,
                            "display_order": 1,
                        }
                    ]
                },
            )
        return database.handle(request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(malformed_categories),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.get("/activity/categories")

    assert response.status_code == 502


def test_database_query_contract_rejects_coercive_counts() -> None:
    database = FakeDatabase()

    def coercive_query(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/activity" and request.method == "QUERY":
            return httpx.Response(
                200,
                json={"activities": [], "total": "0", "limit": "20", "offset": "0"},
            )
        return database.handle(request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(coercive_query),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.get("/activity")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from database service"}


def test_database_summary_contract_rejects_invalid_domain_values() -> None:
    database = FakeDatabase()
    with make_client(database) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        record = database.records[ACTIVITY_ID]
        record["duration_minutes"] = -1
        record["booking_required"] = "false"
        record["categories"] = ["ADVENTURE", "ADVENTURE"]
        response = client.get("/activity")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from database service"}


def test_database_delete_contract_rejects_string_boolean() -> None:
    def coercive_delete(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": ACTIVITY_ID, "deleted": "false"})

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(coercive_delete),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.delete(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 502
    assert response.json() == {"detail": "bad response from database service"}


def test_unreachable_database_dependency_is_a_503() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        message = "offline"
        raise httpx.ConnectError(message, request=request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(unavailable),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.get(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 503
    assert response.json() == {"detail": "database service unavailable"}


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        (
            httpx.Response(500, json={"detail": "failed"}),
            "bad response from database service",
        ),
        (
            httpx.Response(200, content=b"not-json"),
            "bad response from database service",
        ),
    ],
)
def test_bad_database_dependency_responses_are_502(
    upstream: httpx.Response, expected: str
) -> None:
    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(lambda _request: upstream),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.get(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 502
    assert response.json() == {"detail": expected}


def test_health_degrades_when_a_dependency_is_unreachable() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        message = "offline"
        raise httpx.ConnectError(message, request=request)

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(unavailable),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unreachable"


def test_health_degrades_for_a_non_object_dependency_response() -> None:
    def invalid_health(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(invalid_health),
        location_transport=httpx.MockTransport(location_handler),
    )
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unreachable"
