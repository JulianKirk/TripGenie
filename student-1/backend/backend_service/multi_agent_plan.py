"""Student 1's side of the Release 2 "Plan my itinerary" multi-agent workflow.

The shared Multi-Agent Server runs Planner -> Worker -> Reviewer and stops at
`awaiting_human`; it never writes trip data. What it is sent (prompt, schema,
tools, grounding) and what is done with the human's decision both live here
and in BackendService, so Student 1 keeps owning its itinerary rules.
"""

from __future__ import annotations

import json
from typing import Any

FEATURE = "student-1"
PROMPT_ASSET = "itinerary_planner_agents_v1.md"
CORRELATION_PREFIX = "student1-plan-"
ALLOWED_TOOLS = ["trip_get_context", "trips_list_itinerary_items"]
MAX_PLAN_ITEMS = 8
ACTIVE_STATUSES = frozenset({"planning", "working", "reviewing"})
DECIDED_STATUSES = frozenset({"completed", "rejected"})
# The server refuses a context over 4,000 characters of JSON; stay under it.
CONTEXT_MAX_CHARS = 3900
# Every id a trip_get_context result carries: the trip's items and the
# accommodation, activities and transport saved on it.
GROUNDING = {
    "source": FEATURE,
    "id_paths": ["items[].source_id"],
    "id_keys": ["id", "accommodation_id", "activity_id", "transport_id"],
}


def _text_or_null(max_length: int) -> dict[str, object]:
    return {"anyOf": [{"type": "string", "maxLength": max_length}, {"type": "null"}]}


# Sent as the Worker's output schema; PlanDraftItem re-validates every item.
# Plain types and small maxLengths keep Ollama's grammar compiler happy, so
# date and time formats are checked here rather than with schema patterns.
OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "items"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 600},
        "items": {
            "type": "array",
            "maxItems": MAX_PLAN_ITEMS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "date",
                    "start_time",
                    "end_time",
                    "title",
                    "location",
                    "description",
                    "category",
                    "source_id",
                ],
                "properties": {
                    "date": {"type": "string", "minLength": 10, "maxLength": 10},
                    "start_time": _text_or_null(5),
                    "end_time": _text_or_null(5),
                    "title": {"type": "string", "minLength": 1, "maxLength": 120},
                    "location": _text_or_null(200),
                    "description": _text_or_null(400),
                    "category": {
                        "type": "string",
                        "enum": [
                            "accommodation",
                            "transport",
                            "activity",
                            "meal",
                            "note",
                            "other",
                        ],
                    },
                    "source_id": _text_or_null(64),
                },
            },
        },
    },
}


def plan_item_id(run_id: str, index: int) -> str:
    """The id an approved item is saved under: one per run and action index,
    so a repeated decision finds the item it already wrote."""
    return f"item_{run_id}_{index}"


def plan_item_prefix(run_id: str) -> str:
    return f"item_{run_id}_"


def _compact(record: dict[str, Any], limits: dict[str, int]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in record.items():
        if value is None:
            continue
        if key in limits and isinstance(value, str):
            value = value[: limits[key]]
        compact[key] = value
    return compact


def bounded_context(detail: dict[str, Any]) -> dict[str, Any]:
    """The trip and its saved evidence, trimmed to the server's context limit.

    Lists lose their last entries first (the longest list each time), so the
    trimming is deterministic; `truncated` tells the Worker to use its tools.
    """
    trip = _compact(
        {
            key: detail.get(key)
            for key in (
                "id",
                "name",
                "destination",
                "start_date",
                "end_date",
                "traveller_count",
                "notes",
            )
        },
        {"name": 120, "destination": 120, "notes": 300},
    )
    items = [
        _compact(
            {
                "id": item["id"],
                "date": item["date"],
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "title": item["title"],
                "category": item["category"],
            },
            {"title": 80},
        )
        for day in detail.get("days", [])
        for item in day.get("items", [])
    ]
    accommodations = [
        _compact(
            {
                "accommodation_id": stay["accommodation_id"],
                "name": stay.get("name"),
                "check_in": stay["date"],
                "check_in_time": stay.get("check_in_time"),
                "check_out": stay.get("check_out"),
                "check_out_time": stay.get("check_out_time"),
            },
            {"name": 80},
        )
        for stay in detail.get("accommodations", [])
    ]
    activities = [
        _compact(
            {
                "activity_id": activity["activity_id"],
                "name": activity.get("name"),
                "date": activity["date"],
                "start_time": activity.get("start_time"),
                "duration_minutes": activity.get("duration_minutes"),
            },
            {"name": 80},
        )
        for activity in detail.get("activities", [])
    ]
    transport = [
        _compact(
            {
                "transport_id": leg["transport_id"],
                "type": leg.get("type"),
                "origin": leg.get("origin"),
                "destination": leg.get("destination"),
                "departure_time": leg.get("departure_time"),
                "arrival_time": leg.get("arrival_time"),
                "plan_status": leg.get("plan_status"),
            },
            {"origin": 60, "destination": 60},
        )
        for leg in detail.get("transport", [])
    ]
    context: dict[str, Any] = {
        "trip": trip,
        "existing_items": items[:12],
        "accommodations": accommodations[:6],
        "activities": activities[:12],
        "transport": transport[:8],
    }
    if (
        len(items) > 12
        or len(accommodations) > 6
        or len(activities) > 12
        or len(transport) > 8
    ):
        context["truncated"] = True
    lists = ("existing_items", "activities", "transport", "accommodations")
    while len(json.dumps(context)) > CONTEXT_MAX_CHARS:
        longest = max(lists, key=lambda key: len(context[key]))
        if not context[longest]:
            break
        context[longest].pop()
        context["truncated"] = True
    return context


def build_run_request(
    detail: dict[str, Any],
    *,
    task: str,
    worker_system: str,
    correlation_id: str,
) -> dict[str, Any]:
    trip_id = str(detail["id"])
    return {
        "feature": FEATURE,
        "task": task,
        "trip_id": trip_id,
        "context": bounded_context(detail),
        "worker_system": worker_system,
        "output_schema": OUTPUT_SCHEMA,
        "allowed_tools": ALLOWED_TOOLS,
        "grounding": GROUNDING,
        "actions_path": "items",
        "correlation_id": correlation_id,
        "metadata": {"service": "student-1-backend", "trip_id": trip_id},
    }


def _interval(item: dict[str, Any]) -> tuple[str, str] | None:
    start = item.get("start_time")
    if not start:
        return None
    return start, item.get("end_time") or start


def clashes(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Same date and overlapping times; an item without an end is a moment.
    Items without a start time are not compared."""
    if first.get("date") != second.get("date"):
        return False
    a, b = _interval(first), _interval(second)
    if a is None or b is None:
        return False
    return a[0] == b[0] or (a[0] < b[1] and b[0] < a[1])
