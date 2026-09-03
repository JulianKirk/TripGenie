from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from .models import ActivityWrite

if TYPE_CHECKING:
    from starlette.datastructures import FormData

    from .models import ActivityDetail

SCHEDULE_KEY = re.compile(r"^schedules\.(\d+)\.")


def new_activity_form_values() -> dict[str, object]:
    """Return a valid demo activity for fast catalogue creation."""
    return {
        "name": "Example activity",
        "description": "A sample Sydney activity for demonstrating TripGenie.",
        "price": "25.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
        "minimum_participants": 1,
        "maximum_participants": 10,
        "country": "Australia",
        "city": "Sydney",
        "street": "George Street",
        "street_number": 500,
        "categories": ["OUTDOOR", "TOUR"],
        "booking_required": False,
        "wheelchair_accessible": None,
        "step_free_access": None,
        "accessible_toilet": None,
        "availability_schedules": [
            {
                "recurring_weekly": True,
                "day_of_week": "FRIDAY",
                "start_time": "09:00",
                "end_time": "11:00",
            }
        ],
        "is_active": True,
    }


def _text(form: FormData, name: str) -> str | None:
    value = str(form.get(name, "")).strip()
    return value or None


def _integer(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _money(value: str | None) -> str:
    if value is None:
        return ""
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return value
    exponent = decimal.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        return value
    return f"{decimal:.2f}"


def _tri_state(value: str | None) -> bool | str | None:
    if value in {None, "", "unknown"}:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def _schedules(form: FormData) -> list[dict[str, object]]:
    indexes = sorted(
        {
            int(match.group(1))
            for key in form
            if (match := SCHEDULE_KEY.match(str(key))) is not None
        }
    )
    schedules: list[dict[str, object]] = []
    for index in indexes:
        prefix = f"schedules.{index}."
        recurring = _text(form, f"{prefix}recurring_weekly") == "true"
        row: dict[str, object] = {
            "recurring_weekly": recurring,
            "start_time": _text(form, f"{prefix}start_time"),
            "end_time": _text(form, f"{prefix}end_time"),
        }
        optional = "day_of_week" if recurring else "date"
        if value := _text(form, f"{prefix}{optional}"):
            row[optional] = value
        schedules.append(row)
    return schedules


def parse_activity_form(form: FormData) -> ActivityWrite:
    """Build one allow-listed backend write model from browser form fields."""
    payload: dict[str, Any] = {
        "name": _text(form, "name") or "",
        "description": _text(form, "description") or "",
        "price": _money(_text(form, "price")),
        "pricing_basis": _text(form, "pricing_basis") or "",
        "duration_minutes": _integer(_text(form, "duration_minutes")),
        "minimum_participants": _integer(_text(form, "minimum_participants")),
        "booking_required": bool(_text(form, "booking_required")),
        "is_active": bool(_text(form, "is_active")),
        "categories": [
            str(value).strip()
            for value in form.getlist("category")
            if str(value).strip()
        ],
        "location_details": {
            "country": _text(form, "country") or "",
            "city": _text(form, "city") or "",
        },
        "availability_schedules": _schedules(form),
    }
    for name in ("minimum_age", "maximum_age", "maximum_participants"):
        if (value := _integer(_text(form, name))) is not None:
            payload[name] = value
    for name in ("booking_notes", "accessibility_notes"):
        if value := _text(form, name):
            payload[name] = value
    for name in (
        "wheelchair_accessible",
        "step_free_access",
        "accessible_toilet",
    ):
        if (value := _tri_state(_text(form, name))) is not None:
            payload[name] = value

    location = payload["location_details"]
    for name in ("street", "street_number"):
        if value := _text(form, name):
            location[name] = _integer(value) if name == "street_number" else value
    return ActivityWrite.model_validate(payload)


def activity_form_values(activity: ActivityDetail) -> dict[str, object]:
    values = activity.model_dump(mode="json", exclude_none=True)
    values.pop("id", None)
    schedules = values["availability_schedules"]
    for schedule in schedules:
        schedule.pop("id", None)
    location = values.pop("location_details")
    values.update(location)
    return values


def submitted_form_values(form: FormData) -> dict[str, object]:
    values: dict[str, object] = {key: str(value) for key, value in form.multi_items()}
    values["categories"] = [str(value) for value in form.getlist("category")]
    schedules: list[dict[str, str]] = []
    for index in sorted(
        {
            int(match.group(1))
            for key in form
            if (match := SCHEDULE_KEY.match(str(key))) is not None
        }
    ):
        prefix = f"schedules.{index}."
        schedules.append(
            {
                name: str(form.get(f"{prefix}{name}", ""))
                for name in (
                    "recurring_weekly",
                    "day_of_week",
                    "date",
                    "start_time",
                    "end_time",
                )
            }
        )
    values["availability_schedules"] = schedules
    return values
