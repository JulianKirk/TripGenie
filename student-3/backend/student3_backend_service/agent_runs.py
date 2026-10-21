"""Transport planning through the shared Multi-Agent Server (Release 2).

The server's Planner, Worker and Reviewer answer a transport question with the
same prompt, schema and MCP tools as AI suggestions; its deterministic checks
reject an answer citing an id no transport tool returned. This module builds
that run request, turns the server's run record into this feature's view, and
decides what a human decision may add to a trip. The grounding guard is the
same as for AI suggestions: an id is only ever added if a successful Student 3
transport tool in the Worker's final attempt returned it, so a hallucinated id
cannot reach a trip even if a human approves it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .ai_suggestions import TRANSPORT_SOURCE, build_prompt, summarise_tools
from .config import Settings
from .errors import VALIDATION_ERROR_MESSAGE, bad_gateway, validation_error
from .models import (
    AgentCheck,
    AgentHumanDecision,
    AgentPlan,
    AgentReview,
    AgentReviewRequest,
    AgentRunError,
    AgentRunRequest,
    AgentRunView,
    AgentStage,
    AgentSuggestion,
    TransportOptionRecord,
    TransportRecommendationDraft,
    TransportRecommendationRequest,
)

# The read-only transport tools; MCP owns their definitions.
TRANSPORT_TOOLS = [
    "transport_search",
    "transport_get",
    "transport_compare",
    "transport_trip_costs",
]
# Each suggestion is a proposed action: what a human approves gets added.
ACTIONS_PATH = "suggestions"

OptionLookup = Callable[[str], TransportOptionRecord | None]


def build_run_request(
    settings: Settings,
    payload: AgentRunRequest,
) -> dict[str, Any]:
    """The run request: this feature's own prompt, schema, tools and grounding."""
    system, prompt = build_prompt(
        settings,
        TransportRecommendationRequest(
            question=payload.question,
            trip_id=payload.trip_id,
            origin=payload.origin,
            destination=payload.destination,
        ),
    )
    # The prompt's fields become the Worker's context; the server sends the
    # trip itself, so it is not repeated there.
    context = json.loads(prompt)
    context.pop("trip_id", None)
    return {
        "feature": TRANSPORT_SOURCE,
        "task": payload.question,
        "trip_id": payload.trip_id,
        "context": context,
        "worker_system": system,
        "output_schema": TransportRecommendationDraft.model_json_schema(),
        "allowed_tools": TRANSPORT_TOOLS,
        "grounding": {
            "source": TRANSPORT_SOURCE,
            "id_paths": ["suggestions[].transport_id"],
        },
        "actions_path": ACTIONS_PATH,
        "correlation_id": f"student3-agents-{uuid4().hex[:12]}",
        "metadata": {
            "service": settings.service_name,
            "feature": "transport-agents",
        },
    }


def grounded_ids(run: dict[str, Any]) -> set[str]:
    """Ids returned by successful transport tools in the final Worker attempt."""
    workers = [step for step in _steps(run) if step.get("agent") == "worker"]
    if not workers:
        return set()
    tools = summarise_tools(workers[-1].get("tools") or [])
    return {transport_id for trace in tools for transport_id in trace.transport_ids}


def to_view(run: dict[str, Any], lookup: OptionLookup) -> AgentRunView:
    """The server's run record, re-read and narrowed to what this feature shows."""
    try:
        draft = _draft(run)
        grounded = grounded_ids(run)
        suggestions = [
            AgentSuggestion(
                index=index,
                transport_id=item["transport_id"],
                reason=item["reason"],
                grounded=item["transport_id"] in grounded,
                option=lookup(item["transport_id"])
                if item["transport_id"] in grounded
                else None,
            )
            for index, item in enumerate(_suggestions(draft))
        ]
        plan = run.get("plan")
        review = run.get("review")
        human = run.get("human")
        error = run.get("error")
        return AgentRunView(
            run_id=run["run_id"],
            status=run["status"],
            task=run["task"],
            trip_id=run.get("trip_id"),
            attempts=run.get("attempts") or 0,
            created_at=run["created_at"],
            updated_at=run["updated_at"],
            plan=AgentPlan(goal=plan["goal"], steps=plan["steps"]) if plan else None,
            stages=[_stage(step) for step in _steps(run)],
            checks=[
                AgentCheck(
                    name=check["name"],
                    passed=check["passed"],
                    detail=check["detail"],
                )
                for check in run.get("checks") or []
            ],
            review=AgentReview(
                verdict=review["verdict"],
                summary=review["summary"],
                issues=review.get("issues") or [],
                risks=review.get("risks") or [],
                recommendations=review.get("recommendations") or [],
            )
            if review
            else None,
            overview=draft.get("overview") if draft else None,
            considerations=list(draft.get("considerations") or []) if draft else [],
            disclaimer=draft.get("disclaimer") if draft else None,
            suggestions=suggestions,
            human=AgentHumanDecision(
                decision=human["decision"],
                reviewer=human["reviewer"],
                notes=human.get("notes"),
                decided_at=human["decided_at"],
            )
            if human
            else None,
            error=AgentRunError(code=error["code"], message=error["message"])
            if error
            else None,
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise bad_gateway(
            "The Multi-Agent Server returned a run this service cannot read.",
            [{"field": "multi_agent", "issue": "run did not match the contract"}],
        ) from exc


def review_body(
    run: dict[str, Any],
    decision: AgentReviewRequest,
) -> dict[str, Any]:
    """The server's decision body, checked against the run's own suggestions."""
    suggestions = _suggestions(run.get("result"))
    accepted = list(dict.fromkeys(decision.accepted))
    problems: list[dict[str, str]] = []
    if any(index >= len(suggestions) for index in accepted):
        problems.append(
            {
                "field": "accepted",
                "issue": f"must index the run's {len(suggestions)} suggestion(s)",
            },
        )
    if decision.decision == "partial" and not accepted:
        problems.append(
            {"field": "accepted", "issue": "choose at least one suggestion"},
        )
    if decision.decision == "correct" and not (accepted or decision.corrected_overview):
        problems.append(
            {
                "field": "corrected_overview",
                "issue": "give a corrected overview or choose the suggestions to keep",
            },
        )
    grounded = grounded_ids(run)
    if (
        decision.decision != "reject"
        and run.get("trip_id")
        and any(item["transport_id"] in grounded for item in suggestions)
        and decision.traveller_count is None
    ):
        problems.append(
            {
                "field": "traveller_count",
                "issue": "say how many travellers to add to the trip",
            },
        )
    if problems:
        raise validation_error(VALIDATION_ERROR_MESSAGE, problems)

    body: dict[str, Any] = {
        "decision": decision.decision,
        "reviewer": decision.reviewer,
    }
    if decision.notes:
        body["notes"] = decision.notes
    if decision.decision == "partial":
        body["accepted_actions"] = accepted
    if decision.decision == "correct":
        result = dict(run.get("result") or {})
        if decision.corrected_overview:
            result["overview"] = decision.corrected_overview
        if accepted:
            result["suggestions"] = [suggestions[index] for index in accepted]
        body["corrected_result"] = result
    return body


def approved_ids(run: dict[str, Any]) -> list[str]:
    """Transport ids the human approved, in order and without repeats."""
    ids: list[str] = []
    for action in run.get("approved_actions") or []:
        transport_id = action.get("transport_id") if isinstance(action, dict) else None
        if isinstance(transport_id, str) and transport_id not in ids:
            ids.append(transport_id)
    return ids


def _steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in run.get("steps") or [] if isinstance(step, dict)]


def _stage(step: dict[str, Any]) -> AgentStage:
    error = step.get("error") or {}
    return AgentStage(
        agent=step["agent"],
        attempt=step["attempt"],
        status=step["status"],
        duration_ms=max(int(step.get("duration_ms") or 0), 0),
        error_code=error.get("code"),
        error_message=error.get("message"),
        tools=summarise_tools(step.get("tools") or []),
    )


def _draft(run: dict[str, Any]) -> dict[str, Any] | None:
    """The answer the human sees: the signed-off one once a human decided."""
    if run.get("human") and run.get("final_result") is not None:
        return run["final_result"]
    result = run.get("result")
    return result if isinstance(result, dict) else None


def _suggestions(draft: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not draft:
        return []
    return [
        item
        for item in draft.get("suggestions") or []
        if isinstance(item, dict)
        and isinstance(item.get("transport_id"), str)
        and isinstance(item.get("reason"), str)
    ]
