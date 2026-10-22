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
        "agent_stages": agent_stages(result),
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


def agent_stages(result: PlannerResponse) -> list[dict[str, object]]:
    """Use run state for the active agent and recorded steps for finished agents."""
    run = result.run
    active = {"planning": "planner", "working": "worker", "reviewing": "reviewer"}.get(
        run.status
    )
    latest_attempt = max((step.attempt for step in run.steps), default=0)
    attempt = max(1, run.attempts, latest_attempt)
    if run.status == "planning":
        attempt = latest_attempt + 1
    interrupted = None
    if run.status == "failed" and (not run.steps or run.steps[-1].status != "failed"):
        # Timeouts stop the workflow without appending the interrupted stage.
        previous = run.steps[-1].agent if run.steps else None
        interrupted = {
            None: "planner",
            "planner": "worker",
            "worker": "reviewer",
            "reviewer": "planner",
        }[previous]
        if previous == "reviewer":
            attempt = latest_attempt + 1
    stages: list[dict[str, object]] = []
    for name in ("planner", "worker", "reviewer"):
        steps = [step for step in run.steps if step.agent == name]
        current = [step for step in steps if step.attempt == attempt]
        state = (
            "running"
            if active == name
            else (current[-1].status if current else "pending")
        )
        if interrupted == name:
            state = "failed"
        stages.append(
            {
                "agent": name,
                "status": state,
                "label": {
                    "running": "Running",
                    "pending": "Not yet run",
                    "completed": "Completed",
                    "failed": "Failed",
                }[state],
                "steps": steps,
            }
        )
    return stages
