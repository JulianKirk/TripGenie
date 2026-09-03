"""HTTP contract tests using the real service and temporary SQLite."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from student4_database_service.app import create_app
from student4_database_service.config import Settings
from student4_database_service.seed_data import seed_categories

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

EXPECTED_CATEGORY_CODES = [
    "ADVENTURE",
    "CULTURE",
    "FAMILY",
    "FOOD_DRINK",
    "NIGHTLIFE",
    "OUTDOOR",
    "SHOPPING",
    "TOUR",
    "WELLNESS",
    "WILDLIFE",
]

ACTIVITY = {
    "name": "Sydney Harbour walk",
    "description": "A guided walk around the harbour.",
    "price": "45.00",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 60,
    "minimum_age": 8,
    "minimum_participants": 1,
    "maximum_participants": 12,
    "booking_required": True,
    "booking_notes": "Book 24 hours ahead.",
    "wheelchair_accessible": False,
    "step_free_access": False,
    "accessible_toilet": True,
    "location_details": {
        "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
        "city_id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
        "street": "Circular Quay",
    },
    "categories": ["OUTDOOR", "TOUR"],
    "availability_schedules": [
        {
            "recurring_weekly": True,
            "day_of_week": "SATURDAY",
            "start_time": "09:00",
            "end_time": "11:00",
        }
    ],
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'activities.db'}", seed=False
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        with app.state.session_factory() as session:
            seed_categories(session)
        yield test_client


@pytest.fixture
def activity_id(client: TestClient) -> str:
    response = client.post("/internal/activity", json=ACTIVITY)
    assert response.status_code == 201
    return cast("str", response.json()["id"])


def test_health_opens_the_database(client: TestClient) -> None:
    response = client.get("/internal/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "student-4-database"}


def test_health_reports_database_initialization_failure_as_json_500(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'missing' / 'activities.db'}",
        seed=True,
    )

    with TestClient(
        create_app(settings), raise_server_exceptions=False
    ) as failed_client:
        response = failed_client.get("/internal/health")

    assert response.status_code == 500
    assert response.json() == {"detail": "database operation failed"}


def test_database_initialization_recovers_without_restarting_the_app(
    tmp_path: Path,
) -> None:
    database_directory = tmp_path / "missing"
    settings = Settings(
        database_url=f"sqlite:///{database_directory / 'activities.db'}",
        seed=True,
    )

    with TestClient(
        create_app(settings), raise_server_exceptions=False
    ) as recovering_client:
        failed = recovering_client.get("/internal/health")
        database_directory.mkdir()
        recovered = recovering_client.get("/internal/health")
        categories = recovering_client.get("/internal/activity/categories")

    assert failed.status_code == 500
    assert recovered.status_code == 200
    assert recovered.json() == {"status": "ok", "service": "student-4-database"}
    assert [item["code"] for item in categories.json()["categories"]] == (
        EXPECTED_CATEGORY_CODES
    )


def test_categories_are_seeded_in_documented_order(client: TestClient) -> None:
    response = client.get("/internal/activity/categories")
    assert response.status_code == 200
    assert [item["code"] for item in response.json()["categories"]] == (
        EXPECTED_CATEGORY_CODES
    )


def test_create_returns_the_complete_record_with_canonical_values(
    client: TestClient,
) -> None:
    response = client.post("/internal/activity", json=ACTIVITY)
    body = response.json()

    assert response.status_code == 201
    assert body["price"] == "45.00"
    assert body["location_details"]["id"]
    assert body["availability_schedules"][0]["id"]
    assert body["availability_schedules"][0]["start_time"] == "09:00"
    assert "maximum_age" not in body
    assert "accessibility_notes" not in body


def test_get_returns_active_or_inactive_full_record(
    client: TestClient, activity_id: str
) -> None:
    replacement = deepcopy(ACTIVITY)
    replacement["is_active"] = False
    replacement["availability_schedules"] = []
    response = client.put(f"/internal/activity/{activity_id}", json=replacement)
    assert response.status_code == 200

    body = client.get(f"/internal/activity/{activity_id}").json()
    assert body["id"] == activity_id
    assert body["is_active"] is False
    assert body["availability_schedules"] == []


def test_query_returns_summary_and_pagination_metadata(
    client: TestClient, activity_id: str
) -> None:
    response = client.request(
        "QUERY",
        "/internal/activity",
        json={"text": "HARBOUR", "is_active": True, "limit": 10, "offset": 0},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["activities"][0]["id"] == activity_id
    assert "booking_notes" not in body["activities"][0]
    assert "availability_schedules" not in body["activities"][0]
    assert set(body["activities"][0]["location_details"]) == {
        "country_id",
        "city_id",
    }


def test_query_combines_country_city_and_street_filters(
    client: TestClient, activity_id: str
) -> None:
    location = cast("dict[str, object]", ACTIVITY["location_details"])
    response = client.request(
        "QUERY",
        "/internal/activity",
        json={
            "location_details": {
                "country_id": location["country_id"],
                "city_id": location["city_id"],
                "street": "circular",
            }
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["activities"]] == [activity_id]


def test_query_without_a_body_uses_empty_filter_defaults(
    client: TestClient, activity_id: str
) -> None:
    response = client.request("QUERY", "/internal/activity")

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_put_replaces_the_aggregate_and_preserves_owned_ids(
    client: TestClient, activity_id: str
) -> None:
    before = client.get(f"/internal/activity/{activity_id}").json()
    replacement = deepcopy(ACTIVITY)
    replacement.update(
        {
            "name": "Museum visit",
            "categories": ["CULTURE"],
            "availability_schedules": [
                {
                    "recurring_weekly": False,
                    "date": "2026-10-17",
                    "start_time": "10:00",
                    "end_time": "14:00",
                }
            ],
        }
    )

    response = client.put(f"/internal/activity/{activity_id}", json=replacement)
    body = response.json()

    assert response.status_code == 200
    assert body["id"] == activity_id
    assert body["location_details"]["id"] == before["location_details"]["id"]
    previous_schedule_id = before["availability_schedules"][0]["id"]
    assert body["availability_schedules"][0]["id"] != previous_schedule_id
    assert body["categories"] == ["CULTURE"]


def test_delete_removes_the_activity(client: TestClient, activity_id: str) -> None:
    response = client.delete(f"/internal/activity/{activity_id}")
    assert response.status_code == 200
    assert response.json() == {"id": activity_id, "deleted": True}
    assert client.get(f"/internal/activity/{activity_id}").status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_missing_activity_is_404(client: TestClient, method: str) -> None:
    target = f"/internal/activity/{uuid4()}"
    if method == "put":
        response = client.put(target, json=ACTIVITY)
    else:
        response = getattr(client, method)(target)
    assert response.status_code == 404
    assert response.json() == {"detail": "activity not found"}


def test_malformed_or_unknown_input_is_400(client: TestClient) -> None:
    unknown = client.post("/internal/activity", json={**ACTIVITY, "unexpected": True})
    invalid = client.post("/internal/activity", json={**ACTIVITY, "price": "45"})

    assert unknown.status_code == 400
    assert invalid.status_code == 400
    assert isinstance(unknown.json()["detail"], str)


@pytest.mark.parametrize("invalid_date", [1792195200, "2026-10-17T00:00:00"])
def test_dates_require_canonical_iso_date_strings(
    client: TestClient, invalid_date: object
) -> None:
    response = client.request(
        "QUERY",
        "/internal/activity",
        json={"availability": {"date": invalid_date}},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_minutes", "60"),
        ("minimum_participants", True),
        ("booking_required", "false"),
        ("is_active", 1),
    ],
)
def test_primitive_types_are_not_coerced(
    client: TestClient, field: str, value: object
) -> None:
    response = client.post("/internal/activity", json={**ACTIVITY, field: value})

    assert response.status_code == 400


def test_sqlite_integer_overflow_is_rejected_as_json_400(
    client: TestClient,
) -> None:
    payload = deepcopy(ACTIVITY)
    payload["is_active"] = False
    payload["availability_schedules"] = []
    payload["duration_minutes"] = 2**63

    create_response = client.post("/internal/activity", json=payload)
    query_response = client.request(
        "QUERY", "/internal/activity", json={"offset": 2**63}
    )

    assert create_response.status_code == 400
    assert query_response.status_code == 400
    assert isinstance(create_response.json()["detail"], str)
    assert isinstance(query_response.json()["detail"], str)


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_non_uuid_activity_id_is_400(client: TestClient, method: str) -> None:
    target = "/internal/activity/not-a-uuid"
    response = (
        client.put(target, json=ACTIVITY)
        if method == "put"
        else getattr(client, method)(target)
    )

    assert response.status_code == 400
    assert "activity_id" in response.json()["detail"]


def test_category_literal_is_not_swallowed_by_uuid_route(client: TestClient) -> None:
    assert client.get("/internal/activity/categories").status_code == 200
