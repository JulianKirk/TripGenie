from __future__ import annotations

from copy import deepcopy

from student4_frontend_service.models import ActivityDetail, ActivitySummary
from student4_frontend_service.presenters import (
    accessibility_label,
    format_duration,
    format_location,
    format_money,
    group_schedules,
    party_total,
)

from tests.frontend.conftest import DETAIL, SUMMARY


def summary(**changes: object) -> ActivitySummary:
    payload = deepcopy(SUMMARY)
    payload.update(changes)
    return ActivitySummary.model_validate(payload)


def detail() -> ActivityDetail:
    return ActivityDetail.model_validate(deepcopy(DETAIL))


def test_money_and_per_person_party_total_use_exact_decimal_math() -> None:
    activity = summary()

    assert format_money(activity.price) == "AUD 45.00"
    assert party_total(activity, 3) == "AUD 135.00"


def test_flat_admission_party_total_does_not_multiply() -> None:
    activity = summary(price="85.50", pricing_basis="FLAT_ADMISSION")

    assert party_total(activity, 4) == "AUD 85.50"


def test_missing_or_invalid_party_size_has_no_total() -> None:
    activity = summary()

    assert party_total(activity, None) is None
    assert party_total(activity, 0) is None


def test_duration_uses_hours_and_minutes() -> None:
    assert format_duration(120) == "2h"
    assert format_duration(95) == "1h 35m"
    assert format_duration(45) == "45m"


def test_location_uses_only_resolved_names() -> None:
    assert format_location(summary().location_details) == "Sydney, Australia"
    only_city = summary(location_details={"city": "sydney"}).location_details
    assert format_location(only_city) == "Sydney"


def test_accessibility_has_three_truthful_states() -> None:
    assert accessibility_label(True) == "Yes"
    assert accessibility_label(False) == "No"
    assert accessibility_label(None) == "Unknown"


def test_schedules_group_weekly_rows_and_keep_one_off_dates() -> None:
    activity = detail()
    payload = deepcopy(DETAIL["availability_schedules"][0])
    payload.update(
        {
            "id": "55555555-5555-5555-5555-555555555555",
            "recurring_weekly": False,
            "day_of_week": None,
            "date": "2027-04-02",
        }
    )
    activity.availability_schedules.append(
        type(activity.availability_schedules[0]).model_validate(payload)
    )

    grouped = group_schedules(activity.availability_schedules)

    assert grouped.weekly["SATURDAY"][0].start_time.strftime("%H:%M") == "09:00"
    assert grouped.one_off[0].date is not None
    assert grouped.one_off[0].date.isoformat() == "2027-04-02"
