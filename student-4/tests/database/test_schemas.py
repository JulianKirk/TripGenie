"""Behavioral tests for the database service's wire schemas."""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from typing import cast

import pytest
from pydantic import ValidationError
from student4_database_service.schemas import (
    ActivityQueryRequest,
    ActivityWrite,
    ScheduleWrite,
)

VALID_ACTIVITY = {
    "name": "Sydney Harbour walk",
    "description": "A guided walk around the harbour.",
    "price": "45.00",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 60,
    "minimum_age": 8,
    "maximum_age": 80,
    "minimum_participants": 1,
    "maximum_participants": 12,
    "booking_required": True,
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


def _activity(**updates: object) -> dict[str, object]:
    payload = deepcopy(VALID_ACTIVITY)
    payload.update(updates)
    return payload


def test_activity_write_normalises_required_text_and_preserves_exact_money() -> None:
    activity = ActivityWrite.model_validate(
        _activity(name="  Harbour walk  ", description="  Guided.  ")
    )

    assert activity.name == "Harbour walk"
    assert activity.description == "Guided."
    assert activity.model_dump(mode="json")["price"] == "45.00"


@pytest.mark.parametrize("price", [45, 45.0, "45", "45.0", "045.00", "-1.00"])
def test_activity_write_rejects_noncanonical_money(price: object) -> None:
    with pytest.raises(ValidationError):
        ActivityWrite.model_validate(_activity(price=price))


@pytest.mark.parametrize(
    "updates",
    [
        {"duration_minutes": 2**63},
        {"minimum_age": 2**63, "maximum_age": None},
        {"maximum_age": 2**63},
        {"minimum_participants": 2**63, "maximum_participants": None},
        {"maximum_participants": 2**63},
        {
            "location_details": {
                **cast("dict[str, object]", VALID_ACTIVITY["location_details"]),
                "street_number": 2**63,
            }
        },
    ],
)
def test_activity_write_rejects_integers_too_large_for_sqlite(
    updates: dict[str, object],
) -> None:
    payload = _activity(**updates)
    if "duration_minutes" in updates:
        payload.update(is_active=False, availability_schedules=[])

    with pytest.raises(ValidationError):
        ActivityWrite.model_validate(payload)


@pytest.mark.parametrize(
    ("updates", "field"),
    [
        ({"name": "  "}, "name"),
        ({"minimum_age": 12, "maximum_age": 11}, "maximum_age"),
        (
            {"minimum_participants": 4, "maximum_participants": 3},
            "maximum_participants",
        ),
        ({"categories": []}, "categories"),
        ({"categories": ["TOUR", "TOUR"]}, "categories"),
        ({"categories": ["UNKNOWN"]}, "categories.0"),
        ({"is_active": True, "availability_schedules": []}, "availability_schedules"),
    ],
)
def test_activity_write_rejects_invalid_aggregate(
    updates: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        ActivityWrite.model_validate(_activity(**updates))

    locations = [
        ".".join(str(item) for item in error["loc"]) for error in caught.value.errors()
    ]
    assert any(field in location for location in locations)


@pytest.mark.parametrize(
    "schedule",
    [
        {
            "recurring_weekly": True,
            "date": "2026-10-17",
            "start_time": "09:00",
            "end_time": "11:00",
        },
        {
            "recurring_weekly": False,
            "day_of_week": "SATURDAY",
            "start_time": "09:00",
            "end_time": "11:00",
        },
        {
            "recurring_weekly": True,
            "day_of_week": "SATURDAY",
            "start_time": "11:00",
            "end_time": "09:00",
        },
    ],
)
def test_activity_write_rejects_invalid_schedule_discriminators(
    schedule: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ActivityWrite.model_validate(_activity(availability_schedules=[schedule]))


def test_activity_write_rejects_interval_shorter_than_activity() -> None:
    schedules = [
        {
            "recurring_weekly": True,
            "day_of_week": "SATURDAY",
            "start_time": "09:00",
            "end_time": "09:59",
        }
    ]

    with pytest.raises(ValidationError, match="duration"):
        ActivityWrite.model_validate(_activity(availability_schedules=schedules))


def test_activity_write_rejects_duplicate_schedules() -> None:
    schedules = cast(
        "list[dict[str, object]]", VALID_ACTIVITY["availability_schedules"]
    )
    schedule = schedules[0]

    with pytest.raises(ValidationError, match="duplicate"):
        ActivityWrite.model_validate(
            _activity(availability_schedules=[schedule, deepcopy(schedule)])
        )


def test_inactive_activity_may_have_no_schedule() -> None:
    activity = ActivityWrite.model_validate(
        _activity(is_active=False, availability_schedules=[])
    )

    assert activity.availability_schedules == []


@pytest.mark.parametrize(
    "payload",
    [
        {"price": {"min": "20.00", "max": "10.00"}},
        {"duration_minutes": {"min": 60, "max": 30}},
        {"youngest_age": 18, "oldest_age": 12},
        {"categories": {"codes": []}},
        {"categories": {"codes": ["TOUR", "TOUR"]}},
        {"availability": {"date": "2026-10-17", "start_time": "09:00"}},
        {
            "availability": {
                "date": "2026-10-17",
                "start_time": "10:00",
                "end_time": "09:00",
            }
        },
        {"unexpected": True},
    ],
)
def test_query_rejects_contradictory_or_unknown_filters(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ActivityQueryRequest.model_validate(payload)


def test_query_defaults_are_stable_and_city_does_not_require_country() -> None:
    location = cast("dict[str, object]", VALID_ACTIVITY["location_details"])
    query = ActivityQueryRequest.model_validate(
        {"location_details": {"city_id": location["city_id"]}}
    )

    assert query.limit == 20
    assert query.offset == 0
    assert query.sort.value == "NAME_ASC"
    assert query.location_details is not None
    assert query.location_details.country_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"duration_minutes": {"min": 2**63}},
        {"duration_minutes": {"max": 2**63}},
        {"party_size": 2**63},
        {"youngest_age": 2**63},
        {"oldest_age": 2**63},
        {"offset": 2**63},
    ],
)
def test_query_rejects_integers_too_large_for_sqlite(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ActivityQueryRequest.model_validate(payload)


@pytest.mark.parametrize("bound", ["min", "max"])
def test_duration_range_accepts_zero(bound: str) -> None:
    query = ActivityQueryRequest.model_validate({"duration_minutes": {bound: 0}})

    assert query.duration_minutes is not None
    assert getattr(query.duration_minutes, bound) == 0


def test_schedule_accepts_a_typed_date_from_persistence() -> None:
    schedule = ScheduleWrite.model_validate(
        {
            "recurring_weekly": False,
            "date": dt.date(2026, 10, 17),
            "start_time": "09:00",
            "end_time": "11:00",
        }
    )

    assert schedule.date == dt.date(2026, 10, 17)
