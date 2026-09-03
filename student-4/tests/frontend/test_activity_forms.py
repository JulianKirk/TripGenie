from __future__ import annotations

import pytest
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile
from student4_frontend_service.forms import parse_activity_form


def complete_form(**replacements: str) -> FormData:
    values: list[tuple[str, str | UploadFile]] = [
        ("name", "Harbour Kayak"),
        ("description", "Guided paddle on Sydney Harbour."),
        ("price", "89.5"),
        ("pricing_basis", "PER_PERSON"),
        ("duration_minutes", "120"),
        ("minimum_age", "8"),
        ("maximum_age", "70"),
        ("minimum_participants", "1"),
        ("maximum_participants", "12"),
        ("booking_required", "on"),
        ("booking_notes", "Book one day ahead."),
        ("wheelchair_accessible", "false"),
        ("step_free_access", "unknown"),
        ("accessible_toilet", "true"),
        ("accessibility_notes", "Ask staff for the accessible route."),
        ("is_active", "on"),
        ("country", "Australia"),
        ("city", "Sydney"),
        ("street", "George Street"),
        ("street_number", "1"),
        ("category", "ADVENTURE"),
        ("category", "OUTDOOR"),
        ("schedules.0.recurring_weekly", "true"),
        ("schedules.0.day_of_week", "MONDAY"),
        ("schedules.0.date", ""),
        ("schedules.0.start_time", "09:00"),
        ("schedules.0.end_time", "12:00"),
        ("schedules.1.recurring_weekly", "false"),
        ("schedules.1.day_of_week", ""),
        ("schedules.1.date", "2027-04-02"),
        ("schedules.1.start_time", "13:00"),
        ("schedules.1.end_time", "15:00"),
        ("ignored_admin_flag", "yes"),
    ]
    if replacements:
        values = [(name, replacements.get(name, value)) for name, value in values]
    return FormData(values)


def form_post_data(form: FormData) -> dict[str, str | list[str]]:
    result: dict[str, str | list[str]] = {}
    for key in form:
        values = [str(value) for value in form.getlist(key)]
        result[key] = values if len(values) > 1 else values[0]
    return result


def test_complete_form_builds_exact_backend_write() -> None:
    model = parse_activity_form(complete_form())

    assert model.model_dump(mode="json", exclude_none=True) == {
        "name": "Harbour Kayak",
        "description": "Guided paddle on Sydney Harbour.",
        "price": "89.50",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
        "minimum_age": 8,
        "maximum_age": 70,
        "minimum_participants": 1,
        "maximum_participants": 12,
        "booking_required": True,
        "booking_notes": "Book one day ahead.",
        "wheelchair_accessible": False,
        "accessible_toilet": True,
        "accessibility_notes": "Ask staff for the accessible route.",
        "is_active": True,
        "categories": ["ADVENTURE", "OUTDOOR"],
        "location_details": {
            "country": "Australia",
            "city": "Sydney",
            "street": "George Street",
            "street_number": 1,
        },
        "availability_schedules": [
            {
                "recurring_weekly": True,
                "day_of_week": "MONDAY",
                "start_time": "09:00",
                "end_time": "12:00",
            },
            {
                "recurring_weekly": False,
                "date": "2027-04-02",
                "start_time": "13:00",
                "end_time": "15:00",
            },
        ],
    }


def test_unchecked_booleans_and_blank_optionals_are_omitted_or_false() -> None:
    form = complete_form(
        booking_required="",
        is_active="",
        minimum_age="",
        maximum_age="",
        maximum_participants="",
        street="",
        street_number="",
        booking_notes="",
        accessibility_notes="",
    )

    model = parse_activity_form(form)

    assert model.booking_required is False
    assert model.is_active is False
    assert model.minimum_age is None
    assert model.maximum_age is None
    assert model.location_details.street is None


def test_invalid_price_is_not_rounded_away() -> None:
    with pytest.raises(ValidationError, match="canonical decimal"):
        parse_activity_form(complete_form(price="10.123"))


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ({"name": "   "}, "at least 1 character"),
        ({"maximum_age": "7"}, "maximum_age must be at least minimum_age"),
        (
            {"maximum_participants": "0"},
            "greater than or equal to 1",
        ),
        ({"category": "MADE_UP"}, "Input should be"),
        ({"duration_minutes": "300"}, "fit the activity duration"),
    ],
)
def test_backend_write_invariants_are_checked_before_sending(
    replacement: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_activity_form(complete_form(**replacement))


def test_active_activity_requires_a_schedule() -> None:
    form = FormData(
        [
            item
            for item in complete_form().multi_items()
            if not item[0].startswith("schedules.")
        ]
    )

    with pytest.raises(ValidationError, match="active activities require"):
        parse_activity_form(form)
