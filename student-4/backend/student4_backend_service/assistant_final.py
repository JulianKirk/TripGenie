"""Resolve final cards from fresh MCP data and author checked recommendations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .assistant_constraints import party_total
from .assistant_models import ActivityPart, TextPart
from .assistant_tools import AgentError
from .schemas import Activity

if TYPE_CHECKING:
    from .assistant_constraints import RequestConstraints
    from .assistant_models import FinalAction
    from .assistant_tools import ToolExecutor

MAX_CARDS = 6


def _checked_text(
    executor: ToolExecutor, constraints: RequestConstraints, excluded: int
) -> str:
    text = constraints.summary()
    if excluded:
        text += (
            " Some proposed cards were excluded because they did not meet "
            "the checked constraints."
        )
    if not executor.result.activities:
        text += " No verified activity cards remained in the inspected results."
    if constraints.party_size is not None:
        for index, activity in enumerate(executor.result.activities.values(), 1):
            total = activity.price
            if activity.pricing_basis == "PER_PERSON":
                total = party_total(total, constraints.party_size)
            detail = f" Card {index} party total: AUD {total:.2f}."
            if len(text) + len(detail) <= 1000:
                text += detail
    return text.strip()


async def resolve_cards(
    action: FinalAction,
    executor: ToolExecutor,
    constraints: RequestConstraints,
    *,
    eligible_ids: set[str],
    activity_data_requested: bool,
) -> None:
    references = [part for part in action.parts if isinstance(part, ActivityPart)]
    if len(references) > MAX_CARDS:
        message = "The assistant returned too many activity cards."
        raise AgentError(message)
    ids = list(dict.fromkeys(str(part.activity_id) for part in references))
    checked = constraints.summary()
    if not ids and checked and activity_data_requested:
        ids = sorted(eligible_ids)[:MAX_CARDS]
    if any(value not in executor.known_ids for value in ids):
        message = (
            "The assistant referenced an activity outside this request's tool results."
        )
        raise AgentError(message)
    excluded = 0
    for activity_id in ids:
        value = await executor.call("activities_get", {"activity_id": activity_id})
        if value["ok"]:
            activity = Activity.model_validate(value["data"])
            if constraints.accepts(activity):
                executor.result.activities[activity_id] = activity
            else:
                excluded += 1
        else:
            executor.result.unavailable_activity_ids.append(activity_id)
    executor.result.parts = action.parts
    if (checked and (activity_data_requested or ids)) or excluded:
        executor.result.parts = [
            TextPart(type="text", text=_checked_text(executor, constraints, excluded))
        ]
        executor.result.parts.extend(
            ActivityPart(type="activity", activity_id=activity.id)
            for activity in executor.result.activities.values()
        )
    elif constraints.price_min is not None or constraints.price_max is not None:
        executor.result.parts = [
            TextPart(
                type="text",
                text=(
                    "I cannot verify activity recommendations against this budget "
                    "because no activity data was requested."
                ),
            )
        ]
    executor.result.status = "complete"
