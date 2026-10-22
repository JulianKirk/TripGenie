"""Accommodation planning through the shared Multi-Agent Server (Release 2).

The server's Planner, Worker and Reviewer answer an accommodation question with
this feature's prompt and schema and the shared MCP accommodation tools; its
deterministic checks reject an answer citing an id no tool returned. This module
builds that run request, turns the server's run record into this feature's view
and decides what a human decision may add to a trip.

The grounding guard: an id is only ever added to a trip if a successful
accommodation tool in the Worker's *final* attempt returned it, so a
hallucinated id cannot reach a trip even if a human approves it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import ValidationError

from backend_service.agent_schemas import (
    AccommodationRecommendationDraft,
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
    AgentToolCall,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from backend_service.config import Settings
    from backend_service.schemas import Accommodation

SOURCE = "student-2"
# The read-only accommodation tools; MCP owns their definitions.
ACCOMMODATION_TOOLS = [
    "accommodations_search",
    "accommodations_get",
    "accommodations_committed_costs",
]
# Tools whose results are listings, so whose ids may ground a suggestion.
LISTING_TOOLS = {"accommodations_search", "accommodations_get"}
# Each suggestion is a proposed action: what a human approves gets added.
ACTIONS_PATH = "suggestions"
# The server caps the context at 4,000 characters of JSON.
MAX_PLACES = 40
BAD_RUN = "The Multi-Agent Server returned a run this service cannot read."


def _worker_system() -> str:
    from importlib import resources

    return (
        resources.files("backend_service")
        .joinpath("prompts", "accommodation_agents_v1.md")
        .read_text(encoding="utf-8")
        .strip()
    )


def build_run_request(
    settings: Settings,
    payload: AgentRunRequest,
    countries: list[str],
    cities: list[str],
) -> dict[str, Any]:
    """The run request: this feature's own prompt, schema, tools and grounding."""
    context: dict[str, Any] = {
        "known_countries": countries[:MAX_PLACES],
        "known_cities": cities[:MAX_PLACES],
    }
    if payload.country:
        context["country"] = payload.country
    if payload.city:
        context["city"] = payload.city
    return {
        "feature": SOURCE,
        "task": payload.question,
        "trip_id": payload.trip_id,
        "context": context,
        "worker_system": _worker_system(),
        "output_schema": AccommodationRecommendationDraft.model_json_schema(),
        "allowed_tools": ACCOMMODATION_TOOLS,
        "grounding": {
            "source": SOURCE,
            "id_paths": ["suggestions[].accommodation_id"],
        },
        "actions_path": ACTIONS_PATH,
        "correlation_id": f"student2-agents-{uuid4().hex[:12]}",
        "metadata": {
            "service": settings.service_name,
            "feature": "accommodation-agents",
        },
    }


def _steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in run.get("steps") or [] if isinstance(step, dict)]


def _listing_ids(trace: dict[str, Any]) -> list[str]:
    """Student 2 listing ids in one successful tool result, in result order."""
    if (
        trace.get("status") != "success"
        or trace.get("tool") not in LISTING_TOOLS
        or not isinstance(trace.get("result"), dict)
    ):
        return []
    envelope = trace["result"].get("structuredContent")
    if (
        not isinstance(envelope, dict)
        or envelope.get("ok") is not True
        or envelope.get("source") != SOURCE
        or not isinstance(envelope.get("data"), dict)
    ):
        return []
    data = envelope["data"]
    if isinstance(data.get("items"), list):  # search
        rows = data["items"]
    elif "id" in data:  # a single listing
        rows = [data]
    else:
        rows = []
    return [
        row["id"].lower()
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def grounded_ids(run: dict[str, Any]) -> set[str]:
    """Ids returned by successful accommodation tools in the final Worker attempt."""
    workers = [step for step in _steps(run) if step.get("agent") == "worker"]
    if not workers:
        return set()
    return {
        listing_id
        for trace in workers[-1].get("tools") or []
        if isinstance(trace, dict)
        for listing_id in _listing_ids(trace)
    }


def _tool_call(trace: dict[str, Any]) -> AgentToolCall:
    state = trace.get("status")
    return AgentToolCall(
        tool=str(trace.get("tool", "unknown")),
        arguments=trace["arguments"]
        if isinstance(trace.get("arguments"), dict)
        else {},
        status=state if state in {"success", "rejected"} else "error",
        duration_ms=max(int(trace.get("duration_ms") or 0), 0),
        error=str(trace["error"]) if trace.get("error") else None,
        accommodation_ids=_listing_ids(trace),
    )


def _stage(step: dict[str, Any]) -> AgentStage:
    error = step.get("error") or {}
    return AgentStage(
        agent=step["agent"],
        attempt=step["attempt"],
        status=step["status"],
        duration_ms=max(int(step.get("duration_ms") or 0), 0),
        error_code=error.get("code"),
        error_message=error.get("message"),
        tools=[
            _tool_call(trace)
            for trace in step.get("tools") or []
            if isinstance(trace, dict)
        ],
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
        and isinstance(item.get("accommodation_id"), str)
        and isinstance(item.get("reason"), str)
    ]


async def to_view(
    run: dict[str, Any],
    lookup: Callable[[str], Awaitable[Accommodation | None]],
) -> AgentRunView:
    """The server's run record, re-read and narrowed to what this feature shows."""
    try:
        draft = _draft(run)
        grounded = grounded_ids(run)
        suggestions = []
        for index, item in enumerate(_suggestions(draft)):
            listing_id = item["accommodation_id"]
            is_grounded = listing_id.lower() in grounded
            suggestions.append(
                AgentSuggestion(
                    index=index,
                    accommodation_id=listing_id,
                    reason=item["reason"],
                    grounded=is_grounded,
                    accommodation=await lookup(listing_id) if is_grounded else None,
                )
            )
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
                    name=check["name"], passed=check["passed"], detail=check["detail"]
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
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RUN) from exc


def _problem(
    decision: AgentReviewRequest, accepted: list[int], offered: int
) -> str | None:
    """Why a decision cannot be sent, or None."""
    if any(index >= offered for index in accepted):
        return f"accepted must index the run's {offered} suggestion(s)"
    if decision.decision == "partial" and not accepted:
        return "choose at least one suggestion to accept"
    if decision.decision == "correct" and not (accepted or decision.corrected_overview):
        return "give a corrected overview or choose the suggestions to keep"
    if (
        decision.check_in
        and decision.check_out
        and decision.check_out < decision.check_in
    ):
        return "check_out must not be before check_in"
    return None


def review_body(run: dict[str, Any], decision: AgentReviewRequest) -> dict[str, Any]:
    """The server's decision body, checked against the run's own suggestions."""
    suggestions = _suggestions(run.get("result"))
    accepted = list(dict.fromkeys(decision.accepted))
    problem = _problem(decision, accepted, len(suggestions))
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)

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
    """Listing ids the human approved, in order and without repeats."""
    ids: list[str] = []
    for action in run.get("approved_actions") or []:
        listing_id = (
            action.get("accommodation_id") if isinstance(action, dict) else None
        )
        if isinstance(listing_id, str) and listing_id not in ids:
            ids.append(listing_id)
    return ids


def request_json(body: dict[str, Any]) -> str:
    """For logging and tests: the request as the server receives it."""
    return json.dumps(body, sort_keys=True)
