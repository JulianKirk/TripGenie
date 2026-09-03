from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from .models import ActivitySummary, PublicLocation, Schedule


def format_money(value: Decimal) -> str:
    return f"${value:.2f}"


def party_total(activity: ActivitySummary, party_size: int | None) -> str | None:
    if party_size is None or party_size < 1:
        return None
    total = (
        activity.price * party_size
        if activity.pricing_basis == "PER_PERSON"
        else activity.price
    )
    return format_money(total)


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def format_location(location: PublicLocation) -> str:
    values = [value.title() for value in (location.city, location.country) if value]
    return ", ".join(values)


def accessibility_label(value: bool | None) -> str:
    if value is None:
        return "Unknown"
    return "Yes" if value else "No"


@dataclass(frozen=True, slots=True)
class ScheduleGroups:
    weekly: dict[str, list[Schedule]]
    one_off: list[Schedule]


def group_schedules(schedules: list[Schedule]) -> ScheduleGroups:
    weekly: dict[str, list[Schedule]] = {}
    one_off: list[Schedule] = []
    for schedule in schedules:
        if schedule.recurring_weekly and schedule.day_of_week:
            weekly.setdefault(schedule.day_of_week, []).append(schedule)
        else:
            one_off.append(schedule)
    return ScheduleGroups(weekly=weekly, one_off=one_off)
