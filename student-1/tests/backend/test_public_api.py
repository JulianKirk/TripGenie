from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from backend_service.trip_rules import (
    MAX_TRIP_DURATION_DAYS,
    MAX_TRIP_DURATION_DEPENDENCY_MESSAGE,
    MAX_TRIP_DURATION_VALIDATION_ISSUE,
    inclusive_trip_day_count,
)


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


def test_trip_crud_and_day_by_day_detail(client) -> None:
    create_response = client.post("/api/trips", json=create_trip_payload())

    assert create_response.status_code == 201
    created_trip = create_response.json()["data"]
    assert created_trip["id"].startswith("trip_")
    assert [day["date"] for day in created_trip["days"]] == [
        "2027-05-01",
        "2027-05-02",
        "2027-05-03",
        "2027-05-04",
    ]
    assert all(day["items"] == [] for day in created_trip["days"])

    trip_id = created_trip["id"]
    get_response = client.get(f"/api/trips/{trip_id}")
    assert get_response.status_code == 200
    assert get_response.json()["data"] == created_trip

    patch_response = client.patch(
        f"/api/trips/{trip_id}",
        json={
            "destination": "Canberra Region",
            "end_date": "2027-05-05",
            "status": "active",
            "notes": "Lock in museum tickets before arrival.",
        },
    )
    assert patch_response.status_code == 200
    patched_trip = patch_response.json()["data"]
    assert patched_trip["destination"] == "Canberra Region"
    assert patched_trip["end_date"] == "2027-05-05"
    assert patched_trip["status"] == "active"
    assert patched_trip["days"][-1]["date"] == "2027-05-05"

    delete_response = client.delete(f"/api/trips/{trip_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"data": {"id": trip_id, "deleted": True}}

    missing_response = client.get(f"/api/trips/{trip_id}")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "NOT_FOUND"


def test_trip_duration_limit_applies_to_create_requests(client, database_api) -> None:
    allowed_response = client.post(
        "/api/trips",
        json=create_trip_payload(
            id="trip_duration_boundary_01",
            start_date="2027-01-01",
            end_date="2028-01-01",
        ),
    )

    assert allowed_response.status_code == 201
    allowed_trip = allowed_response.json()["data"]
    assert len(allowed_trip["days"]) == MAX_TRIP_DURATION_DAYS
    assert allowed_trip["days"][0]["date"] == "2027-01-01"
    assert allowed_trip["days"][-1]["date"] == "2028-01-01"
    assert database_api.trip_create_calls == 1

    oversized_response = client.post(
        "/api/trips",
        json=create_trip_payload(
            id="trip_duration_over_limit_01",
            start_date="2027-01-01",
            end_date="2028-01-02",
        ),
    )

    assert oversized_response.status_code == 422
    assert oversized_response.json()["error"]["details"] == [
        {"field": "end_date", "issue": MAX_TRIP_DURATION_VALIDATION_ISSUE},
    ]
    assert database_api.trip_create_calls == 1


def test_get_trip_rejects_oversized_upstream_trip_before_day_expansion(
    client,
    database_api,
) -> None:
    trip_id = "trip_legacy_duration_over_limit_01"
    database_api.trips[trip_id] = {
        "id": trip_id,
        "name": "Legacy Long-Haul Journey",
        "destination": "Everywhere",
        "start_date": "2027-01-01",
        "end_date": "2028-01-02",
        "traveller_count": 2,
        "status": "planned",
        "notes": "Legacy data predates the backend duration guardrail.",
    }

    response = client.get(f"/api/trips/{trip_id}")
    duration = inclusive_trip_day_count("2027-01-01", "2028-01-02")

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "BAD_GATEWAY",
            "message": MAX_TRIP_DURATION_DEPENDENCY_MESSAGE,
            "details": [
                {
                    "field": "database",
                    "issue": (
                        f"trip '{trip_id}' spans {duration} days; maximum supported "
                        f"duration is {MAX_TRIP_DURATION_DAYS} days"
                    ),
                },
            ],
        },
    }
    assert database_api.itinerary_item_list_requests == []


def test_trip_duration_limit_validates_effective_patch_state_before_write(
    client,
    database_api,
) -> None:
    trip_id = "trip_patch_duration_limit_01"
    create_response = client.post(
        "/api/trips",
        json=create_trip_payload(
            id=trip_id,
            start_date="2027-01-01",
            end_date="2027-01-03",
        ),
    )
    assert create_response.status_code == 201

    allowed_patch_response = client.patch(
        f"/api/trips/{trip_id}",
        json={"end_date": "2028-01-01"},
    )

    assert allowed_patch_response.status_code == 200
    allowed_trip = allowed_patch_response.json()["data"]
    assert len(allowed_trip["days"]) == MAX_TRIP_DURATION_DAYS
    assert allowed_trip["days"][-1]["date"] == "2028-01-01"
    assert database_api.trip_update_calls == 1

    oversized_patch_response = client.patch(
        f"/api/trips/{trip_id}",
        json={"end_date": "2028-01-02"},
    )

    assert oversized_patch_response.status_code == 422
    assert oversized_patch_response.json()["error"]["details"] == [
        {"field": "end_date", "issue": MAX_TRIP_DURATION_VALIDATION_ISSUE},
    ]
    assert database_api.trip_update_calls == 1


def test_trip_listing_filters_and_selected_day_route(client) -> None:
    list_response = client.get("/api/trips?status=planned")
    assert list_response.status_code == 200
    assert [trip["id"] for trip in list_response.json()["data"]] == [
        "trip_2027_sydney_getaway",
    ]

    destination_response = client.get("/api/trips?destination=tokyo")
    assert destination_response.status_code == 200
    assert [trip["id"] for trip in destination_response.json()["data"]] == [
        "trip_2027_tokyo_city_break",
    ]

    detail_response = client.get("/api/trips/trip_2027_sydney_getaway")
    assert detail_response.status_code == 200
    assert [day["date"] for day in detail_response.json()["data"]["days"]] == [
        "2027-04-01",
        "2027-04-02",
        "2027-04-03",
    ]
    assert detail_response.json()["data"]["days"][0]["items"][0]["id"] == (
        "item_2027_sydney_dinner"
    )

    selected_day_response = client.get(
        "/api/trips/trip_2027_sydney_getaway/days/2027-04-02",
    )
    assert selected_day_response.status_code == 200
    assert selected_day_response.json()["data"] == {
        "trip_id": "trip_2027_sydney_getaway",
        "date": "2027-04-02",
        "items": [
            {
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
        ],
    }


def test_itinerary_item_crud_filtering_and_ordering(client) -> None:
    trip_id = "trip_backend_items_01"
    trip_response = client.post(
        "/api/trips",
        json=create_trip_payload(
            id=trip_id,
            start_date="2027-06-01",
            end_date="2027-06-03",
        ),
    )
    assert trip_response.status_code == 201

    note_response = client.post(
        f"/api/trips/{trip_id}/itinerary-items",
        json=create_item_payload(
            id="item_backend_note_01",
            date="2027-06-02",
            start_time=None,
            end_time=None,
            title="Parking Reminder",
            category="note",
        ),
    )
    breakfast_response = client.post(
        f"/api/trips/{trip_id}/itinerary-items",
        json=create_item_payload(
            id="item_backend_breakfast_01",
            date="2027-06-02",
            start_time="08:00",
            end_time="09:00",
            title="Breakfast Booking",
            category="meal",
        ),
    )
    walk_response = client.post(
        f"/api/trips/{trip_id}/itinerary-items",
        json=create_item_payload(
            id="item_backend_walk_01",
            date="2027-06-01",
            start_time="10:00",
            end_time="11:30",
            title="Lake Walk",
            category="activity",
        ),
    )

    assert note_response.status_code == 201
    assert breakfast_response.status_code == 201
    assert walk_response.status_code == 201

    list_response = client.get(f"/api/trips/{trip_id}/itinerary-items")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["data"]] == [
        "item_backend_walk_01",
        "item_backend_breakfast_01",
        "item_backend_note_01",
    ]

    filtered_response = client.get(
        f"/api/trips/{trip_id}/itinerary-items?date=2027-06-02&category=meal",
    )
    assert filtered_response.status_code == 200
    assert [item["id"] for item in filtered_response.json()["data"]] == [
        "item_backend_breakfast_01",
    ]

    get_response = client.get("/api/itinerary-items/item_backend_breakfast_01")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["title"] == "Breakfast Booking"

    patch_response = client.patch(
        "/api/itinerary-items/item_backend_breakfast_01",
        json={"end_time": "09:30", "notes": "Confirm vegetarian option."},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["data"]["end_time"] == "09:30"
    assert patch_response.json()["data"]["notes"] == "Confirm vegetarian option."

    day_response = client.get(f"/api/trips/{trip_id}/days/2027-06-02")
    assert day_response.status_code == 200
    assert [item["id"] for item in day_response.json()["data"]["items"]] == [
        "item_backend_breakfast_01",
        "item_backend_note_01",
    ]

    delete_response = client.delete("/api/itinerary-items/item_backend_walk_01")
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "data": {"id": "item_backend_walk_01", "deleted": True},
    }

    missing_response = client.get("/api/itinerary-items/item_backend_walk_01")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "NOT_FOUND"


def test_validation_errors_cover_domain_rules_and_effective_patch_state(client) -> None:
    invalid_trip_response = client.post(
        "/api/trips",
        json=create_trip_payload(traveller_count=0),
    )
    assert invalid_trip_response.status_code == 422
    assert invalid_trip_response.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_window_response = client.post(
        "/api/trips",
        json=create_trip_payload(start_date="2027-05-05", end_date="2027-05-01"),
    )
    assert invalid_window_response.status_code == 422
    assert invalid_window_response.json()["error"]["details"] == [
        {"field": "start_date", "issue": "must be on or before end_date"},
    ]

    invalid_item_date_response = client.post(
        "/api/trips/trip_2027_sydney_getaway/itinerary-items",
        json=create_item_payload(
            id="item_backend_invalid_trip_window_01",
            date="2027-04-05",
        ),
    )
    assert invalid_item_date_response.status_code == 422
    assert invalid_item_date_response.json()["error"]["details"] == [
        {
            "field": "date",
            "issue": "must fall between 2027-04-01 and 2027-04-03",
        },
    ]

    invalid_item_time_response = client.post(
        "/api/trips/trip_2027_sydney_getaway/itinerary-items",
        json=create_item_payload(
            id="item_backend_invalid_time_01",
            date="2027-04-02",
            start_time="11:00",
            end_time="10:00",
        ),
    )
    assert invalid_item_time_response.status_code == 422
    assert invalid_item_time_response.json()["error"]["details"] == [
        {
            "field": "start_time",
            "issue": "must be earlier than end_time when both are provided",
        },
    ]

    invalid_trip_patch_response = client.patch(
        "/api/trips/trip_2027_sydney_getaway",
        json={"end_date": "2027-04-01"},
    )
    assert invalid_trip_patch_response.status_code == 422
    assert "cannot exclude existing itinerary item dates" in (
        invalid_trip_patch_response.json()["error"]["details"][0]["issue"]
    )

    invalid_item_patch_response = client.patch(
        "/api/itinerary-items/item_2027_sydney_harbour_walk",
        json={"date": "2027-03-31"},
    )
    assert invalid_item_patch_response.status_code == 422
    assert invalid_item_patch_response.json()["error"]["details"] == [
        {
            "field": "date",
            "issue": "must fall between 2027-04-01 and 2027-04-03",
        },
    ]

    empty_patch_response = client.patch(
        "/api/trips/trip_2027_sydney_getaway",
        json={},
    )
    assert empty_patch_response.status_code == 422
    assert empty_patch_response.json()["error"]["details"] == [
        {"field": "body", "issue": "at least one field must be provided"},
    ]


def test_rejects_unsupported_query_params_and_invalid_filters(client) -> None:
    unsupported_response = client.get("/api/trips?unexpected=value")
    assert unsupported_response.status_code == 400
    assert unsupported_response.json()["error"]["code"] == "BAD_REQUEST"

    invalid_filter_response = client.get(
        "/api/trips/trip_2027_sydney_getaway/itinerary-items?category=festival",
    )
    assert invalid_filter_response.status_code == 422
    assert invalid_filter_response.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_date_response = client.get(
        "/api/trips/trip_2027_sydney_getaway/itinerary-items?date=20270402",
    )
    assert invalid_date_response.status_code == 422
    assert invalid_date_response.json()["error"]["details"] == [
        {
            "field": "date",
            "issue": "must be a valid ISO date in YYYY-MM-DD format",
        },
    ]

    invalid_day_response = client.get(
        "/api/trips/trip_2027_sydney_getaway/days/20270402",
    )
    assert invalid_day_response.status_code == 422
    assert invalid_day_response.json()["error"]["details"] == [
        {
            "field": "date",
            "issue": "must be a valid ISO date in YYYY-MM-DD format",
        },
    ]

    blank_query_response = client.get("/api/trips?destination=%20%20%20")
    assert blank_query_response.status_code == 422
    assert blank_query_response.json()["error"]["details"] == [
        {"field": "destination", "issue": "must not be blank"},
    ]


def test_upstream_4xx_errors_are_translated_without_swallowing_details(client) -> None:
    duplicate_trip_response = client.post(
        "/api/trips",
        json=create_trip_payload(id="trip_2027_sydney_getaway"),
    )
    assert duplicate_trip_response.status_code == 409
    assert duplicate_trip_response.json() == {
        "error": {
            "code": "CONFLICT",
            "message": "Trip 'trip_2027_sydney_getaway' already exists.",
            "details": [{"field": "id", "issue": "already exists"}],
        },
    }

    missing_item_response = client.delete("/api/itinerary-items/item_missing_case_01")
    assert missing_item_response.status_code == 404
    assert missing_item_response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Itinerary item 'item_missing_case_01' was not found.",
            "details": [{"field": "id", "issue": "resource does not exist"}],
        },
    }


@pytest.mark.parametrize(
    ("handler_factory", "path", "status_code", "code"),
    [
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ConnectError("boom", request=request),
            ),
            "/api/trips",
            503,
            "DEPENDENCY_UNAVAILABLE",
        ),
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout("slow", request=request),
            ),
            "/api/trips",
            504,
            "DEPENDENCY_TIMEOUT",
        ),
        (
            lambda request: httpx.Response(200, text="{not json"),
            "/api/trips",
            502,
            "BAD_GATEWAY",
        ),
        (
            lambda request: httpx.Response(404, json={"oops": "bad-shape"}),
            "/api/trips/trip_2027_sydney_getaway",
            502,
            "BAD_GATEWAY",
        ),
    ],
)
def test_dependency_failures_and_malformed_upstream_responses_are_explicit(
    client_factory,
    handler_factory,
    path: str,
    status_code: int,
    code: str,
) -> None:
    with client_factory(handler_factory) as client:
        response = client.get(path)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_health_and_ready_reflect_dependency_state(client) -> None:
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {
        "data": {
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
        },
    }

    ready_response = client.get("/ready")
    assert ready_response.status_code == 200
    assert ready_response.json()["data"]["status"] == "ok"


@pytest.mark.parametrize(
    ("handler", "expected_database_status", "expected_ready_status"),
    [
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ConnectError("boom", request=request),
            ),
            "unavailable",
            503,
        ),
        (
            lambda request: httpx.Response(200, text="{oops"),
            "invalid_response",
            503,
        ),
        (
            lambda request: error_response(
                503,
                "DATABASE_BUSY",
                "The database is busy processing another write request. Please retry.",
            ),
            "busy",
            503,
        ),
    ],
)
def test_health_is_degraded_when_database_dependency_is_unhealthy(
    client_factory,
    handler,
    expected_database_status: str,
    expected_ready_status: int,
) -> None:
    with client_factory(handler) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")

    assert health_response.status_code == 200
    assert health_response.json()["data"]["status"] == "degraded"
    assert (
        health_response.json()["data"]["dependencies"]["database"]["status"]
        == expected_database_status
    )
    assert ready_response.status_code == expected_ready_status
    assert ready_response.json()["data"]["status"] == "unavailable"


def test_backend_service_has_no_direct_sqlite_access() -> None:
    package_root = Path(__file__).resolve().parents[2] / "backend" / "backend_service"
    offending_imports: list[str] = []

    for file_path in package_root.rglob("*.py"):
        module = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sqlite3" or alias.name.startswith("sqlite3."):
                        offending_imports.append(str(file_path))
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                offending_imports.append(str(file_path))

    assert offending_imports == []
