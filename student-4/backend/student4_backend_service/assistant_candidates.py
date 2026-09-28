"""Filter bounded MCP observations without changing the raw execution trace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .schemas import Activity, ActivitySummary

if TYPE_CHECKING:
    from .assistant_constraints import RequestConstraints
    from .assistant_tools import ToolExecutor


async def checked_observation(
    name: str,
    value: dict[str, Any],
    constraints: RequestConstraints,
    executor: ToolExecutor,
) -> dict[str, Any]:
    if not value["ok"]:
        return value
    if name == "activities_get":
        if not constraints.accepts(Activity.model_validate(value["data"])):
            return {
                "ok": False,
                "error": "CONSTRAINT_MISMATCH",
                "detail": "Activity does not meet the checked request constraints.",
            }
        return value
    if name != "activities_search":
        return value
    rows = value["data"]["items"]
    accepted = []
    unavailable = 0
    for row in rows[:6]:
        summary = ActivitySummary.model_validate(
            {
                key: item
                for key, item in row.items()
                if key in ActivitySummary.model_fields
            }
        )
        if not constraints.accepts_summary(summary):
            continue
        if constraints.start_date is not None:
            detail = await executor.call(
                "activities_get", {"activity_id": str(summary.id)}
            )
            if not detail["ok"]:
                unavailable += 1
                continue
            if not constraints.accepts(Activity.model_validate(detail["data"])):
                continue
        accepted.append(summary.model_dump(mode="json", exclude_none=True))
    return {
        **value,
        "data": {
            **value["data"],
            "items": accepted,
            "count": len(accepted),
            "catalogue_items_checked": min(len(rows), 6),
            "excluded_by_constraints": min(len(rows), 6) - len(accepted) - unavailable,
            "unavailable_for_checks": unavailable,
            "context_items_omitted": max(0, len(rows) - 6),
            "truncated": bool(value["data"].get("truncated")) or len(rows) > 6,
        },
    }
