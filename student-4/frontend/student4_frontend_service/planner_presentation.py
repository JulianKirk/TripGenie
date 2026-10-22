"""Present structured execution evidence without interpreting model prose."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .planner_models import PlannerResponse


def presentation(result: PlannerResponse) -> dict[str, object]:
    found: dict[str, str] = {}
    for call in result.answer.tools:
        if call.status != "success" or call.result is None:
            continue
        envelope = call.result.get("structuredContent")
        if (
            not isinstance(envelope, dict)
            or envelope.get("source") != "student-4"
            or envelope.get("ok") is not True
        ):
            continue
        data = envelope.get("data")
        if not isinstance(data, dict):
            continue
        rows = data.get("items", [data])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                continue
            try:
                key = str(UUID(str(row.get("id"))))
            except ValueError:
                continue
            found[key] = row["name"]
    return {
        "found_activities": found,
        "decision_names": {
            **found,
            **{
                key: activity.name for key, activity in result.answer.activities.items()
            },
        },
        "show_narrative": not any(
            item.decision == "reject" for item in result.item_decisions
        ),
    }
