"""Repository behavior against a real SQLite database."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from student4_database_service import seed_data
from student4_database_service.enums import CategoryCode
from student4_database_service.models import (
    Activity,
    ActivityAvailabilitySchedule,
    ActivityCategory,
    Category,
    LocationDetails,
)
from student4_database_service.repository import ActivityRepository
from student4_database_service.schemas import ActivityQueryRequest, ActivityWrite
from student4_database_service.seed_data import CATEGORY_SEEDS, seed_categories

from tests.database.conftest import MELBOURNE, SYDNEY

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


def test_category_seed_is_idempotent_and_returns_documented_order(
    session: Session, activities: ActivityRepository
) -> None:
    assert seed_categories(session) == 0
    assert [item.code.value for item in activities.list_categories()] == (
        EXPECTED_CATEGORY_CODES
    )
    assert len(activities.list_categories()) == len(CATEGORY_SEEDS)


def test_seed_database_populates_at_least_ten_rows_per_table(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        assert seed_data.seed_database(session) == 20

        for model in (
            Activity,
            LocationDetails,
            Category,
            ActivityCategory,
            ActivityAvailabilitySchedule,
        ):
            count = session.scalar(select(func.count()).select_from(model))
            assert count is not None
            assert count >= 10

        assert seed_data.seed_database(session) == 0


def test_seed_repairs_missing_categories_without_overwriting_existing_values(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        session.add(
            Category(
                code=CategoryCode.ADVENTURE,
                label="Custom adventure",
                description="Existing value",
                display_order=999,
            )
        )
        session.commit()

        assert seed_data.seed_database(session) == 19
        existing = session.get(Category, CategoryCode.ADVENTURE)
        assert existing is not None
        assert existing.label == "Custom adventure"
        assert len(ActivityRepository(session).list_categories()) == 10


def test_seed_preserves_existing_catalogue_while_repairing_categories(
    session_factory: sessionmaker[Session],
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    with session_factory() as session:
        seed_categories(session)
        repository = ActivityRepository(session)
        sentinel = repository.add(activity_payload(name="Existing catalogue item"))
        category = session.get(Category, CategoryCode.NIGHTLIFE)
        assert category is not None
        session.delete(category)
        session.commit()

        assert seed_data.seed_database(session) == 1
        rows, total = repository.search(ActivityQueryRequest())
        assert total == 1
        assert [row.id for row in rows] == [sentinel.id]
        assert session.get(Category, CategoryCode.NIGHTLIFE) is not None


def test_seed_city_ids_match_the_shared_location_contract() -> None:
    expected_city_ids = [
        "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
        "bc37aae2-9766-5646-93dd-09fc42211aa6",
        "ac89c567-77ce-5c03-b764-f54d6c0d5cea",
        "4cbde40d-2241-55c6-80f2-8e714e7b9cd0",
        "50097d54-8fcd-52d3-867e-a1491b538f38",
        "b6b18900-77fa-5ca3-957b-9b2ce5ee5e84",
        "7b6c8b96-dc8b-5c70-afaf-be854d10c8c4",
        "19a552d3-4191-5f2b-a4ed-db910fc5eb9c",
        "93b2c6d6-5d0e-5151-ae7d-685e08aab942",
        "6b831972-3b36-5af8-a491-78f597f89c18",
    ]
    actual_city_ids = [
        str(cast(dict[str, object], payload["location_details"])["city_id"])
        for payload in seed_data.SAMPLE_ACTIVITY_DATA
    ]

    assert actual_city_ids == expected_city_ids


def test_repository_contains_populated_sqlite_database() -> None:
    database_path = Path(__file__).resolve().parents[2] / "database" / "activities.db"

    assert database_path.is_file()
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        counts: dict[str, int] = {}
        for table in (
            "activities",
            "location_details",
            "categories",
            "activity_categories",
            "activity_availability_schedules",
        ):
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert row is not None
            count = row[0]
            assert count is not None
            counts[table] = count
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        seeded_places = connection.execute(
            """
            SELECT activities.name, location_details.city_id
            FROM activities
            JOIN location_details ON location_details.activity_id = activities.id
            ORDER BY activities.name
            """
        ).fetchall()

    assert all(count >= 10 for count in counts.values()), counts
    assert integrity == ("ok",)
    assert foreign_key_issues == []
    assert [(name, str(UUID(city_id))) for name, city_id in seeded_places] == [
        ("Barossa Valley tasting tour", "4cbde40d-2241-55c6-80f2-8e714e7b9cd0"),
        ("Blue Mountains family hike", "50097d54-8fcd-52d3-867e-a1491b538f38"),
        (
            "Brisbane riverside sunrise yoga",
            "19a552d3-4191-5f2b-a4ed-db910fc5eb9c",
        ),
        (
            "Canberra national gallery visit",
            "6b831972-3b36-5af8-a491-78f597f89c18",
        ),
        (
            "Darwin sunset wildlife cruise",
            "7b6c8b96-dc8b-5c70-afaf-be854d10c8c4",
        ),
        (
            "Great Barrier Reef snorkelling",
            "ac89c567-77ce-5c03-b764-f54d6c0d5cea",
        ),
        (
            "Melbourne museum discovery",
            "bc37aae2-9766-5646-93dd-09fc42211aa6",
        ),
        ("Perth evening food crawl", "93b2c6d6-5d0e-5151-ae7d-685e08aab942"),
        (
            "Salamanca Market food walk",
            "b6b18900-77fa-5ca3-957b-9b2ce5ee5e84",
        ),
        (
            "Sydney Harbour guided walk",
            "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
        ),
    ]


def test_add_and_get_round_trip_the_complete_aggregate(
    activities: ActivityRepository, activity_payload: Callable[..., ActivityWrite]
) -> None:
    created = activities.add(activity_payload())
    loaded = activities.get(created.id)

    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.price == Decimal("45.00")
    assert loaded.location_details.id == created.location_details.id
    assert loaded.location_details.city_id == UUID(SYDNEY["city_id"])
    assert loaded.categories == [CategoryCode.OUTDOOR, CategoryCode.TOUR]
    assert len(loaded.availability_schedules) == 1
    assert loaded.availability_schedules[0].id is not None
    assert loaded.model_dump(mode="json", exclude_none=True)["price"] == "45.00"


def test_add_rejects_categories_that_are_not_seeded_without_partial_rows(
    session: Session, activity_payload: Callable[..., ActivityWrite]
) -> None:
    session.delete(session.get(Category, CategoryCode.TOUR))
    session.commit()
    repository = ActivityRepository(session)

    with pytest.raises(ValueError, match="unsupported category"):
        repository.add(activity_payload())

    assert session.scalar(select(func.count()).select_from(Activity)) == 0
    assert session.scalar(select(func.count()).select_from(LocationDetails)) == 0


def test_replace_preserves_activity_and_location_ids_but_replaces_children(
    activities: ActivityRepository, activity_payload: Callable[..., ActivityWrite]
) -> None:
    before = activities.add(activity_payload())
    replacement = activity_payload(
        name="Museum visit",
        categories=["CULTURE"],
        availability_schedules=[
            {
                "recurring_weekly": False,
                "date": "2026-10-17",
                "start_time": "10:00",
                "end_time": "14:00",
            }
        ],
    )

    after = activities.replace(before.id, replacement)

    assert after is not None
    assert after.id == before.id
    assert after.location_details.id == before.location_details.id
    assert after.availability_schedules[0].id != before.availability_schedules[0].id
    assert after.name == "Museum visit"
    assert after.categories == [CategoryCode.CULTURE]


def test_replace_allows_an_unchanged_schedule_identity(
    activities: ActivityRepository, activity_payload: Callable[..., ActivityWrite]
) -> None:
    before = activities.add(activity_payload())

    after = activities.replace(before.id, activity_payload(name="Updated name"))

    assert after is not None
    assert after.name == "Updated name"
    assert after.availability_schedules[0].id != before.availability_schedules[0].id


def test_failed_replace_keeps_previous_aggregate(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    created = activities.add(activity_payload())
    session.delete(session.get(Category, CategoryCode.CULTURE))
    session.commit()

    with pytest.raises(ValueError, match="unsupported category"):
        activities.replace(
            created.id,
            activity_payload(name="Changed", categories=["CULTURE"]),
        )

    loaded = activities.get(created.id)
    assert loaded is not None
    assert loaded.name == "Harbour walk"
    assert loaded.categories == [CategoryCode.OUTDOOR, CategoryCode.TOUR]


def test_failed_replacement_flush_rolls_back_for_the_same_session(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    created = activities.add(activity_payload())
    session.execute(
        text(
            """
            CREATE TRIGGER reject_schedule_delete
            BEFORE DELETE ON activity_availability_schedules
            BEGIN
                SELECT RAISE(ABORT, 'schedule deletion rejected');
            END
            """
        )
    )
    session.commit()

    with pytest.raises(IntegrityError, match="schedule deletion rejected"):
        activities.replace(created.id, activity_payload(name="Changed"))

    loaded = activities.get(created.id)
    assert loaded is not None
    assert loaded.name == "Harbour walk"
    assert loaded.categories == [CategoryCode.OUTDOOR, CategoryCode.TOUR]


def test_delete_cascades_to_every_owned_child(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    created = activities.add(activity_payload())

    assert activities.delete(created.id) is True
    assert activities.delete(uuid4()) is False
    assert session.scalar(select(func.count()).select_from(Activity)) == 0
    assert session.scalar(select(func.count()).select_from(LocationDetails)) == 0
    assert session.scalar(select(func.count()).select_from(ActivityCategory)) == 0
    assert (
        session.scalar(select(func.count()).select_from(ActivityAvailabilitySchedule))
        == 0
    )


@pytest.fixture
def catalogue(
    activities: ActivityRepository, activity_payload: Callable[..., ActivityWrite]
) -> dict[str, object]:
    harbour = activities.add(activity_payload())
    museum = activities.add(
        activity_payload(
            name="Melbourne Museum",
            description="Culture and natural history galleries.",
            price="20.00",
            pricing_basis="FLAT_ADMISSION",
            duration_minutes=120,
            minimum_age=None,
            maximum_age=None,
            minimum_participants=2,
            maximum_participants=None,
            booking_required=False,
            wheelchair_accessible=True,
            step_free_access=False,
            accessible_toilet=True,
            location_details={**MELBOURNE, "street": "Nicholson Street"},
            categories=["CULTURE"],
            availability_schedules=[
                {
                    "recurring_weekly": False,
                    "date": "2026-10-17",
                    "start_time": "10:00",
                    "end_time": "14:00",
                }
            ],
        )
    )
    draft = activities.add(
        activity_payload(
            name="Secret garden",
            description="Inactive outdoor draft.",
            price="10.00",
            duration_minutes=30,
            is_active=False,
            categories=["OUTDOOR"],
            availability_schedules=[],
        )
    )
    return {"harbour": harbour.id, "museum": museum.id, "draft": draft.id}


def _search_names(
    activities: ActivityRepository, **query: object
) -> tuple[list[str], int]:
    rows, total = activities.search(ActivityQueryRequest.model_validate(query))
    return [row.name for row in rows], total


def test_empty_query_returns_active_and_inactive_records(
    activities: ActivityRepository, catalogue: dict[str, object]
) -> None:
    names, total = _search_names(activities)
    assert names == ["Harbour walk", "Melbourne Museum", "Secret garden"]
    assert total == 3


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"text": "GALLERIES"}, ["Melbourne Museum"]),
        (
            {"location_details": {"city_id": SYDNEY["city_id"]}},
            ["Harbour walk", "Secret garden"],
        ),
        ({"location_details": {"street": "olson str"}}, ["Melbourne Museum"]),
        ({"categories": {"codes": ["TOUR"]}}, ["Harbour walk"]),
        (
            {"categories": {"codes": ["OUTDOOR", "TOUR"], "match": "ALL"}},
            ["Harbour walk"],
        ),
        (
            {"price": {"min": "15.00", "max": "45.00"}},
            ["Harbour walk", "Melbourne Museum"],
        ),
        ({"duration_minutes": {"min": 90}}, ["Melbourne Museum"]),
        ({"party_size": 1}, ["Harbour walk", "Secret garden"]),
        ({"party_size": 11}, ["Melbourne Museum"]),
        ({"youngest_age": 5}, ["Melbourne Museum"]),
        ({"oldest_age": 90}, ["Melbourne Museum"]),
        ({"booking_required": True}, ["Harbour walk", "Secret garden"]),
        ({"booking_required": False}, ["Melbourne Museum"]),
        (
            {"accessibility": {"step_free_access": True}},
            ["Harbour walk", "Secret garden"],
        ),
        (
            {"accessibility": {"accessible_toilet": True}},
            ["Melbourne Museum"],
        ),
        ({"is_active": False}, ["Secret garden"]),
    ],
)
def test_search_filters(
    activities: ActivityRepository,
    catalogue: dict[str, object],
    query: dict[str, object],
    expected: list[str],
) -> None:
    names, _ = _search_names(activities, **query)
    assert names == expected


def test_search_filters_stack(
    activities: ActivityRepository, catalogue: dict[str, object]
) -> None:
    names, total = _search_names(
        activities,
        text="harbour",
        categories={"codes": ["OUTDOOR"]},
        price={"max": "50.00"},
        party_size=4,
        is_active=True,
    )
    assert names == ["Harbour walk"]
    assert total == 1


@pytest.mark.parametrize(
    "location",
    [
        {"country_id": SYDNEY["country_id"], "city_id": SYDNEY["city_id"]},
        {
            "country_id": SYDNEY["country_id"],
            "city_id": SYDNEY["city_id"],
            "street": "circular",
        },
    ],
)
def test_location_filter_combines_multiple_fields(
    activities: ActivityRepository,
    catalogue: dict[str, object],
    location: dict[str, object],
) -> None:
    names, total = _search_names(activities, location_details=location)

    assert names == ["Harbour walk", "Secret garden"]
    assert total == 2


def test_availability_matches_weekly_and_one_off_schedules(
    activities: ActivityRepository, catalogue: dict[str, object]
) -> None:
    names, _ = _search_names(
        activities, availability={"date": "2026-10-17"}, is_active=True
    )
    assert names == ["Harbour walk", "Melbourne Museum"]


def test_availability_requires_duration_to_fit_the_intersection(
    activities: ActivityRepository, catalogue: dict[str, object]
) -> None:
    names, _ = _search_names(
        activities,
        availability={
            "date": "2026-10-17",
            "start_time": "11:00",
            "end_time": "13:00",
        },
        is_active=True,
    )
    assert names == ["Melbourne Museum"]


def test_availability_rejects_a_requested_window_shorter_than_duration(
    activities: ActivityRepository, catalogue: dict[str, object]
) -> None:
    names, _ = _search_names(
        activities,
        availability={
            "date": "2026-10-17",
            "start_time": "09:30",
            "end_time": "10:00",
        },
        is_active=True,
    )
    assert names == []


@pytest.mark.parametrize(
    "query",
    [
        {"text": "%"},
        {"text": "_"},
        {"location_details": {"street": "%"}},
        {"location_details": {"street": "_"}},
    ],
)
def test_substring_filters_treat_sql_wildcards_as_literals(
    activities: ActivityRepository,
    catalogue: dict[str, object],
    query: dict[str, object],
) -> None:
    names, total = _search_names(activities, **query)
    assert names == []
    assert total == 0


@pytest.mark.parametrize(
    "query",
    [
        {"text": "café"},
        {"text": "brûlée"},
        {"location_details": {"street": "école"}},
    ],
)
def test_substring_filters_are_unicode_case_insensitive(
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
    query: dict[str, object],
) -> None:
    activities.add(
        activity_payload(
            name="CAFÉ tour",
            description="Taste CRÈME BRÛLÉE.",
            location_details={**SYDNEY, "street": "Rue de l'ÉCOLE"},
        )
    )

    names, total = _search_names(activities, **query)

    assert names == ["CAFÉ tour"]
    assert total == 1


def test_sort_pagination_and_total_are_deterministic(
    activities: ActivityRepository, catalogue: dict[str, object]
) -> None:
    rows, total = activities.search(
        ActivityQueryRequest(sort="PRICE_DESC", limit=1, offset=1)
    )
    assert [row.name for row in rows] == ["Melbourne Museum"]
    assert total == 3


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("NAME_ASC", ["Harbour walk", "Melbourne Museum", "Secret garden"]),
        ("PRICE_ASC", ["Secret garden", "Melbourne Museum", "Harbour walk"]),
        ("PRICE_DESC", ["Harbour walk", "Melbourne Museum", "Secret garden"]),
        ("DURATION_ASC", ["Secret garden", "Harbour walk", "Melbourne Museum"]),
        ("DURATION_DESC", ["Melbourne Museum", "Harbour walk", "Secret garden"]),
    ],
)
def test_every_documented_sort_mode(
    activities: ActivityRepository,
    catalogue: dict[str, object],
    sort: str,
    expected: list[str],
) -> None:
    names, _ = _search_names(activities, sort=sort)
    assert names == expected


def test_price_filters_and_sorting_remain_exact_for_large_decimals(
    activities: ActivityRepository, activity_payload: Callable[..., ActivityWrite]
) -> None:
    activities.add(activity_payload(name="Two dollars", price="2.00"))
    activities.add(activity_payload(name="Ten dollars", price="10.00"))
    activities.add(activity_payload(name="Large lower", price="9007199254740992.01"))
    activities.add(activity_payload(name="Large upper", price="9007199254740992.02"))

    rows, _ = activities.search(ActivityQueryRequest(sort="PRICE_ASC", limit=100))
    assert [row.name for row in rows] == [
        "Two dollars",
        "Ten dollars",
        "Large lower",
        "Large upper",
    ]
    names, total = _search_names(activities, price={"max": "9007199254740992.01"})
    assert names == ["Large lower", "Ten dollars", "Two dollars"]
    assert total == 3


@pytest.mark.parametrize(
    ("column", "invalid"),
    [
        ("price", "1x.23"),
        ("price", "01.00"),
        ("price", "1.0"),
        ("price", "-1.00"),
        ("pricing_basis", "NOT_A_BASIS"),
    ],
)
def test_database_rejects_invalid_activity_scalars(
    session: Session, column: str, invalid: str
) -> None:
    values = {
        "id": uuid4().hex,
        "name": "Invalid",
        "description": "Bypasses the API on purpose.",
        "price": "1.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 60,
        "minimum_participants": 1,
        "booking_required": 0,
        "is_active": 0,
    }
    values[column] = invalid
    statement = text(
        """
        INSERT INTO activities (
            id, name, description, price, pricing_basis, duration_minutes,
            minimum_participants, booking_required, is_active
        ) VALUES (
            :id, :name, :description, :price, :pricing_basis, :duration_minutes,
            :minimum_participants, :booking_required, :is_active
        )
        """
    )

    with pytest.raises(IntegrityError):
        session.execute(statement, values)
        session.commit()
    session.rollback()


@pytest.mark.parametrize(
    "column",
    [
        "booking_required",
        "wheelchair_accessible",
        "step_free_access",
        "accessible_toilet",
        "is_active",
    ],
)
def test_database_rejects_non_boolean_activity_values(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
    column: str,
) -> None:
    activity = activities.add(activity_payload())

    with pytest.raises(IntegrityError):
        session.execute(
            text(f"UPDATE activities SET {column} = 2 WHERE id = :id"),
            {"id": activity.id.hex},
        )
        session.commit()
    session.rollback()


def test_database_rejects_duplicate_weekly_schedule(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    activity = activities.add(activity_payload())

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO activity_availability_schedules (
                    id, activity_id, recurring_weekly, day_of_week,
                    start_time, end_time
                )
                SELECT :id, activity_id, recurring_weekly, day_of_week,
                       start_time, end_time
                FROM activity_availability_schedules
                WHERE activity_id = :activity_id
                """
            ),
            {"id": uuid4().hex, "activity_id": activity.id.hex},
        )
        session.commit()
    session.rollback()


def test_database_rejects_invalid_weekday(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    activity = activities.add(activity_payload())

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO activity_availability_schedules (
                    id, activity_id, recurring_weekly, day_of_week,
                    start_time, end_time
                ) VALUES (
                    :id, :activity_id, 1, 'FUNDAY', '12:00:00', '13:00:00'
                )
                """
            ),
            {"id": uuid4().hex, "activity_id": activity.id.hex},
        )
        session.commit()
    session.rollback()


@pytest.mark.parametrize(
    ("date", "start_time", "end_time"),
    [
        ("not-a-date", "12:00:00", "13:00:00"),
        ("2026-02-30", "12:00:00", "13:00:00"),
        ("2026-10-17", "25:00:00", "26:00:00"),
        ("2026-10-17", "12:00:00", "25:00:00"),
        ("2026-10-17", 12, 13),
        ("2026-10-17", "12:00", "13:00"),
        ("2026-10-17", "12:00:00+01:00", "13:00:00+01:00"),
    ],
)
def test_database_rejects_invalid_schedule_date_or_time(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
    date: str,
    start_time: object,
    end_time: object,
) -> None:
    activity = activities.add(activity_payload())

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO activity_availability_schedules (
                    id, activity_id, recurring_weekly, date, start_time, end_time
                ) VALUES (
                    :id, :activity_id, 0, :date, :start_time, :end_time
                )
                """
            ),
            {
                "id": uuid4().hex,
                "activity_id": activity.id.hex,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        session.commit()
    session.rollback()


def test_database_cascades_children_for_a_direct_activity_delete(
    session: Session,
    activities: ActivityRepository,
    activity_payload: Callable[..., ActivityWrite],
) -> None:
    activity = activities.add(activity_payload())
    session.execute(
        text("DELETE FROM activities WHERE id = :id"), {"id": activity.id.hex}
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(LocationDetails)) == 0
    assert session.scalar(select(func.count()).select_from(ActivityCategory)) == 0
    assert (
        session.scalar(select(func.count()).select_from(ActivityAvailabilitySchedule))
        == 0
    )
