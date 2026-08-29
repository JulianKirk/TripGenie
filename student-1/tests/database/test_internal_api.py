from __future__ import annotations

import sqlite3

import pytest
from database_service.repository import DatabaseService
from database_service.seed_data import SEED_ITINERARY_ITEMS, SEED_TRIPS


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


def test_schema_initialisation_and_seed_data_are_idempotent(
    service: DatabaseService,
    database_path,
) -> None:
    service.initialize()

    with sqlite3.connect(database_path) as connection:
        first_trip_count = connection.execute(
            "SELECT COUNT(*) FROM trips",
        ).fetchone()[0]
        first_item_count = connection.execute(
            "SELECT COUNT(*) FROM itinerary_items",
        ).fetchone()[0]

    service.initialize()

    with sqlite3.connect(database_path) as connection:
        second_trip_count = connection.execute(
            "SELECT COUNT(*) FROM trips",
        ).fetchone()[0]
        second_item_count = connection.execute(
            "SELECT COUNT(*) FROM itinerary_items",
        ).fetchone()[0]
        trip_indexes = set(
            row[1]
            for row in connection.execute("PRAGMA index_list('trips')").fetchall()
        )
        item_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('itinerary_items')",
            ).fetchall()
        }

    assert first_trip_count == len(SEED_TRIPS)
    assert first_item_count == len(SEED_ITINERARY_ITEMS)
    assert second_trip_count == first_trip_count
    assert second_item_count == first_item_count
    assert "idx_trips_status_start_date" in trip_indexes
    assert "idx_itinerary_items_trip_date" in item_indexes
    assert "idx_itinerary_items_trip_category_date" in item_indexes


def test_schema_enforces_foreign_keys(service: DatabaseService, database_path) -> None:
    service.initialize()

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO itinerary_items (
                    id,
                    trip_id,
                    date,
                    start_time,
                    end_time,
                    title,
                    location,
                    description,
                    category,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "item_missing_trip_fk_01",
                    "trip_missing_fk_01",
                    "2027-05-02",
                    "09:00",
                    "10:00",
                    "Invalid FK",
                    None,
                    None,
                    "activity",
                    None,
                ),
            )


def test_health_endpoint_reports_configured_database_path(
    client,
    database_path,
) -> None:
    response = client.get("/internal/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "student-1-database",
        "sqlite_path": str(database_path),
    }


def test_trip_crud_lifecycle(client) -> None:
    create_response = client.post("/internal/trips", json=create_trip_payload())

    assert create_response.status_code == 201
    created_trip = create_response.json()["data"]
    assert created_trip["id"].startswith("trip_")
    assert created_trip["destination"] == "Canberra"

    trip_id = created_trip["id"]
    get_response = client.get(f"/internal/trips/{trip_id}")
    assert get_response.status_code == 200
    assert get_response.json()["data"] == created_trip

    update_response = client.patch(
        f"/internal/trips/{trip_id}",
        json={
            "destination": "Canberra Region",
            "end_date": "2027-05-05",
            "status": "active",
            "notes": "Lock in museum tickets before arrival.",
        },
    )
    assert update_response.status_code == 200
    updated_trip = update_response.json()["data"]
    assert updated_trip["destination"] == "Canberra Region"
    assert updated_trip["end_date"] == "2027-05-05"
    assert updated_trip["status"] == "active"

    delete_response = client.delete(f"/internal/trips/{trip_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"data": {"id": trip_id, "deleted": True}}

    missing_response = client.get(f"/internal/trips/{trip_id}")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "NOT_FOUND"


def test_itinerary_item_crud_filtering_and_ordering(client) -> None:
    trip_id = "trip_filter_trip_01"
    client.post(
        "/internal/trips",
        json=create_trip_payload(
            id=trip_id,
            start_date="2027-06-01",
            end_date="2027-06-03",
        ),
    )

    first_item_response = client.post(
        f"/internal/trips/{trip_id}/itinerary-items",
        json=create_item_payload(
            id="item_filter_trip_01_breakfast",
            date="2027-06-02",
            start_time="08:00",
            end_time="09:00",
            title="Breakfast Booking",
            category="meal",
        ),
    )
    second_item_response = client.post(
        f"/internal/trips/{trip_id}/itinerary-items",
        json=create_item_payload(
            id="item_filter_trip_01_walk",
            date="2027-06-02",
            start_time="10:00",
            end_time="11:00",
            title="Lake Walk",
            category="activity",
        ),
    )
    third_item_response = client.post(
        f"/internal/trips/{trip_id}/itinerary-items",
        json=create_item_payload(
            id="item_filter_trip_01_note",
            date="2027-06-01",
            start_time=None,
            end_time=None,
            title="Parking Reminder",
            category="note",
        ),
    )

    assert first_item_response.status_code == 201
    assert second_item_response.status_code == 201
    assert third_item_response.status_code == 201

    list_response = client.get(f"/internal/trips/{trip_id}/itinerary-items")
    assert list_response.status_code == 200
    listed_ids = [item["id"] for item in list_response.json()["data"]]
    assert listed_ids == [
        "item_filter_trip_01_note",
        "item_filter_trip_01_breakfast",
        "item_filter_trip_01_walk",
    ]

    filtered_response = client.get(
        f"/internal/trips/{trip_id}/itinerary-items?date=2027-06-02&category=meal",
    )
    assert filtered_response.status_code == 200
    filtered_items = filtered_response.json()["data"]
    assert [item["id"] for item in filtered_items] == ["item_filter_trip_01_breakfast"]

    get_response = client.get("/internal/itinerary-items/item_filter_trip_01_breakfast")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["title"] == "Breakfast Booking"

    update_response = client.patch(
        "/internal/itinerary-items/item_filter_trip_01_breakfast",
        json={"end_time": "09:30", "notes": "Confirm vegetarian option."},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["end_time"] == "09:30"
    assert update_response.json()["data"]["notes"] == "Confirm vegetarian option."

    delete_response = client.delete(
        "/internal/itinerary-items/item_filter_trip_01_walk",
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "data": {"id": "item_filter_trip_01_walk", "deleted": True},
    }

    missing_response = client.get("/internal/itinerary-items/item_filter_trip_01_walk")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "NOT_FOUND"


def test_delete_trip_cascades_its_itinerary_items(client) -> None:
    trip_id = "trip_cascade_case_01"
    item_id = "item_cascade_case_01"
    trip_response = client.post(
        "/internal/trips",
        json=create_trip_payload(
            id=trip_id,
            start_date="2027-07-01",
            end_date="2027-07-04",
        ),
    )
    item_response = client.post(
        f"/internal/trips/{trip_id}/itinerary-items",
        json=create_item_payload(id=item_id, date="2027-07-02"),
    )
    assert trip_response.status_code == 201
    assert item_response.status_code == 201

    delete_trip_response = client.delete(f"/internal/trips/{trip_id}")
    assert delete_trip_response.status_code == 200

    deleted_item_response = client.get(f"/internal/itinerary-items/{item_id}")
    assert deleted_item_response.status_code == 404


def test_duplicate_ids_return_409(client) -> None:
    duplicate_trip_response = client.post(
        "/internal/trips",
        json=create_trip_payload(id="trip_2026_sydney_long_weekend"),
    )
    assert duplicate_trip_response.status_code == 409
    assert duplicate_trip_response.json()["error"]["code"] == "CONFLICT"

    duplicate_item_response = client.post(
        "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items",
        json=create_item_payload(id="item_2026_sydney_harbour_walk", date="2026-10-03"),
    )
    assert duplicate_item_response.status_code == 409
    assert duplicate_item_response.json()["error"]["code"] == "CONFLICT"


def test_validation_errors_cover_domain_rules_and_bad_payloads(client) -> None:
    invalid_trip_response = client.post(
        "/internal/trips",
        json=create_trip_payload(traveller_count=0),
    )
    assert invalid_trip_response.status_code == 422
    assert invalid_trip_response.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_window_response = client.post(
        "/internal/trips",
        json=create_trip_payload(start_date="2027-05-05", end_date="2027-05-01"),
    )
    assert invalid_window_response.status_code == 422
    assert invalid_window_response.json()["error"]["details"] == [
        {"field": "start_date", "issue": "must be on or before end_date"},
    ]

    invalid_item_date_response = client.post(
        "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items",
        json=create_item_payload(id="item_invalid_trip_window_01", date="2026-10-10"),
    )
    assert invalid_item_date_response.status_code == 422
    assert invalid_item_date_response.json()["error"]["details"] == [
        {
            "field": "date",
            "issue": "must fall between 2026-10-02 and 2026-10-05",
        },
    ]

    invalid_item_time_response = client.post(
        "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items",
        json=create_item_payload(
            id="item_invalid_time_case_01",
            date="2026-10-03",
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

    invalid_window_update_response = client.patch(
        "/internal/trips/trip_2026_sydney_long_weekend",
        json={"start_date": "2026-10-04"},
    )
    assert invalid_window_update_response.status_code == 422
    assert "cannot exclude existing itinerary item dates" in (
        invalid_window_update_response.json()["error"]["details"][0]["issue"]
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/internal/trips/trip_missing_case_01"),
        ("patch", "/internal/trips/trip_missing_case_01"),
        ("delete", "/internal/trips/trip_missing_case_01"),
        ("get", "/internal/itinerary-items/item_missing_case_01"),
        ("patch", "/internal/itinerary-items/item_missing_case_01"),
        ("delete", "/internal/itinerary-items/item_missing_case_01"),
    ],
)
def test_missing_records_return_404(client, method: str, path: str) -> None:
    kwargs = {"json": {"notes": "should not work"}} if method == "patch" else {}
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_rejects_unsupported_query_params_and_invalid_filters(client) -> None:
    unsupported_response = client.get("/internal/trips?unexpected=value")
    assert unsupported_response.status_code == 400
    assert unsupported_response.json()["error"]["code"] == "BAD_REQUEST"

    invalid_filter_response = client.get(
        "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items?category=festival",
    )
    assert invalid_filter_response.status_code == 422
    assert invalid_filter_response.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_date_response = client.get(
        "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items?date=20261003",
    )
    assert invalid_date_response.status_code == 422
    assert invalid_date_response.json()["error"]["details"] == [
        {
            "field": "date",
            "issue": "must be a valid ISO date in YYYY-MM-DD format",
        },
    ]

    extra_field_response = client.post(
        "/internal/trips",
        json=create_trip_payload(extra="forbidden"),
    )
    assert extra_field_response.status_code == 422
    assert extra_field_response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("/internal/trips?destination=%20%20%20", "destination"),
        ("/internal/trips?status=%20%20", "status"),
        (
            "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items?date=%20%20",
            "date",
        ),
        (
            "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items?category=%20%20",
            "category",
        ),
    ],
)
def test_rejects_blank_after_trim_query_filters(
    client,
    path: str,
    field: str,
) -> None:
    response = client.get(path)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "One or more fields failed validation.",
            "details": [{"field": field, "issue": "must not be blank"}],
        },
    }


def test_query_filters_trim_surrounding_whitespace(client) -> None:
    destination_response = client.get("/internal/trips?destination=%20%20Sydney%20%20")

    assert destination_response.status_code == 200
    assert [trip["id"] for trip in destination_response.json()["data"]] == [
        "trip_2026_sydney_long_weekend",
    ]

    status_response = client.get("/internal/trips?status=%20planned%20")

    assert status_response.status_code == 200
    assert [trip["id"] for trip in status_response.json()["data"]] == [
        "trip_2026_sydney_long_weekend",
        "trip_2027_adelaide_festival_week",
        "trip_2027_tokyo_spring_visit",
        "trip_2027_queenstown_ski_escape",
    ]

    item_response = client.get(
        "/internal/trips/trip_2026_sydney_long_weekend/itinerary-items"
        "?date=%202026-10-03%20&category=%20activity%20",
    )

    assert item_response.status_code == 200
    assert [item["id"] for item in item_response.json()["data"]] == [
        "item_2026_sydney_harbour_walk",
    ]
