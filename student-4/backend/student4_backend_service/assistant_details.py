"""Render explicitly requested detail facts from verified MCP records."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .assistant_final import _checked_text
from .assistant_models import ActivityPart, TextPart
from .schemas import Activity

if TYPE_CHECKING:
    from .assistant_constraints import RequestConstraints
    from .assistant_tools import ToolExecutor


def requested_details(question: str) -> list[str]:
    patterns = {
        "schedule": r"\b(schedule[s]?|weekly|each week|opening hours)\b",
        "booking": (
            r"\bbooking (notes|requirements|conditions)\b"
            r"|\bbefore (booking|i book)\b"
        ),
        "accessibility": r"\baccessibility notes\b",
    }
    return [
        key
        for key, pattern in patterns.items()
        if re.search(pattern, question, re.IGNORECASE)
    ]


def _facts(activity: Activity, fields: list[str]) -> str:
    lines = {
        "Activity": activity.name,
        "Price (AUD)": f"{activity.price:.2f} {activity.pricing_basis}",
        "Duration": f"{activity.duration_minutes} minutes",
        "Participants (min/max)": (
            f"{activity.minimum_participants}/"
            f"{activity.maximum_participants or 'Unknown'}"
        ),
        "Booking required": "Yes" if activity.booking_required else "No",
    }
    if "schedule" in fields:
        schedules = []
        for entry in activity.availability_schedules:
            day = (
                str(entry.day_of_week).title()
                if entry.recurring_weekly
                else str(entry.date)
            )
            start = entry.start_time.strftime("%H:%M")
            end = entry.end_time.strftime("%H:%M")
            schedules.append(f"{day} {start} to {end}")
        lines["Catalogue schedule (local time)"] = (
            "; ".join(schedules) or "Not provided."
        )
    for field in ("booking", "accessibility"):
        if field in fields:
            notes = getattr(activity, f"{field}_notes")
            lines[f"{field.title()} notes"] = notes or "Not provided."
    # Reserve space for every field label, even when a note or schedule is long.
    quota = (900 - sum(len(label) + 3 for label in lines)) // len(lines)
    return "\n".join(
        f"{label}: {_short(value, quota)}" for label, value in lines.items()
    )


def _short(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 12] + " [shortened]"


async def complete_details(
    question: str,
    executor: ToolExecutor,
    constraints: RequestConstraints,
    observations: list[dict[str, Any]],
) -> None:
    fields = requested_details(question)
    if not fields:
        return
    # Reuse agent detail reads. Ordinary card reads are never MCP evidence.
    records = {
        str(item["result"]["data"]["id"]): Activity.model_validate(
            item["result"]["data"]
        )
        for item in observations
        if item["tool"] == "activities_get" and item["result"]["ok"]
    }
    # A direct factual answer can legitimately have no card.
    selected = list(executor.result.activities) or list(records)[:6]
    if not selected:
        return
    parts: list[TextPart | ActivityPart] = []
    for activity_id in selected:
        activity = records.get(activity_id)
        if activity is None:
            value = await executor.call("activities_get", {"activity_id": activity_id})
            if value["ok"]:
                activity = Activity.model_validate(value["data"])
        if activity is None or not constraints.accepts(activity):
            text = "The requested activity details could not be verified through MCP."
        else:
            text = _facts(activity, fields)
        parts.append(TextPart(type="text", text=text))
        if activity_id in executor.result.activities:
            parts.append(ActivityPart(type="activity", activity_id=activity_id))
    if constraints.summary() and parts and isinstance(parts[0], TextPart):
        checked = _checked_text(executor, constraints, 0)
        combined = checked + "\n" + parts[0].text
        if len(combined) > 1000:
            combined = (
                combined[:900] + "\nDetails shortened. Open View details for the rest."
            )
        parts[0] = TextPart(type="text", text=combined)
    executor.result.parts = parts
