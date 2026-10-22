from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway
from .models import (
    AgentCheck,
    AgentHistoryEvent,
    AgentHumanDecision,
    AgentPlan,
    AgentProposedAction,
    AgentReview,
    AgentReviewRequest,
    AgentRunView,
    AgentStage,
    BudgetAgentAction,
    BudgetAgentDraft,
    BudgetRecord,
    ToolTrace,
)

FEATURE = "student-5"
WORKER_PROMPT_ASSET = "budget_agents_v1.md"
ACTIVE_STATUSES = {"planning", "working", "reviewing"}
TERMINAL_STATUSES = {"completed", "rejected", "failed"}
ALLOCATION_CATEGORIES = ("accommodation", "transport", "activities", "food", "other")
SERVER_TRIP_ID = re.compile(r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


def build_run_request(
    settings: Settings, budget: BudgetRecord, question: str, worker_system: str
) -> dict[str, Any]:
    allocations = {
        category: f"{getattr(budget, f'{category}_budget'):.2f}"
        for category in ALLOCATION_CATEGORIES
    }
    return {
        "feature": FEATURE,
        "task": question,
        "trip_id": budget.trip_id if SERVER_TRIP_ID.match(budget.trip_id) else None,
        "context": {
            "budget_id": str(budget.budget_id),
            "budget_trip_id": budget.trip_id,
            "currency": budget.currency,
            "total_budget": f"{budget.total_budget:.2f}",
            "current_allocations": allocations,
        },
        "worker_system": worker_system,
        "output_schema": BudgetAgentDraft.model_json_schema(),
        "grounding": {
            "source": FEATURE,
            "id_paths": ["budget_id"],
            "id_keys": ["budget_id"],
        },
        "actions_path": "actions",
        "correlation_id": f"student5-agents-{uuid4().hex[:12]}",
        "metadata": {
            "service": settings.service_name,
            "feature": "budget-review-agents",
            "budget_id": str(budget.budget_id),
        },
    }


def ensure_feature(run: dict[str, Any], run_id: str) -> None:
    if run.get("feature") != FEATURE:
        raise ApiError(
            404,
            "RUN_NOT_FOUND",
            f"Run '{run_id}' is not a budget review run.",
            [{"field": "run_id", "issue": "belongs to another feature"}],
        )


def _steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in run.get("steps") or [] if isinstance(step, dict)]


def _draft(run: dict[str, Any]) -> dict[str, Any] | None:
    if run.get("human") and isinstance(run.get("final_result"), dict):
        return run["final_result"]
    result = run.get("result")
    return result if isinstance(result, dict) else None


def _valid_actions(draft: dict[str, Any] | None) -> list[BudgetAgentAction | None]:
    actions: list[BudgetAgentAction | None] = []
    for item in (draft or {}).get("actions") or []:
        try:
            actions.append(BudgetAgentAction.model_validate(item))
        except ValidationError:
            actions.append(None)
    return actions


def tool_budget_ids(run: dict[str, Any]) -> set[str]:
    workers = [step for step in _steps(run) if step.get("agent") == "worker"]
    if not workers:
        return set()
    ids: set[str] = set()
    for trace in workers[-1].get("tools") or []:
        result = trace.get("result") if isinstance(trace, dict) else None
        envelope = result.get("structuredContent") if isinstance(result, dict) else None
        if (
            trace.get("status") != "success"
            or not isinstance(envelope, dict)
            or envelope.get("ok") is not True
            or envelope.get("source") != FEATURE
        ):
            continue
        data = envelope.get("data")
        if isinstance(data, dict):
            records = [data, *(data.get("budgets") or [])]
            ids.update(
                str(item["budget_id"])
                for item in records
                if isinstance(item, dict) and "budget_id" in item
            )
    return ids


def is_grounded(run: dict[str, Any], budget_id: UUID) -> bool:
    draft = _draft(run)
    return (
        draft is not None
        and draft.get("budget_id") == str(budget_id)
        and str(budget_id) in tool_budget_ids(run)
    )


def to_view(
    run: dict[str, Any],
    budget: BudgetRecord,
    history: list[dict[str, Any]] | None = None,
) -> AgentRunView:
    try:
        draft = _draft(run)
        plan = run.get("plan")
        review = run.get("review")
        human = run.get("human")
        actions = [
            AgentProposedAction(
                index=index,
                category=action.category,
                current_allocation=(
                    f"{getattr(budget, f'{action.category}_budget'):.2f}"
                ),
                new_allocation=action.new_allocation,
                reason=action.reason,
            )
            for index, action in enumerate(_valid_actions(draft))
            if action is not None
        ]
        overview = draft.get("overview") if draft else None
        return AgentRunView(
            run_id=run["run_id"],
            status=run["status"],
            active=run["status"] in ACTIVE_STATUSES,
            task=run["task"],
            attempts=run.get("attempts") or 0,
            created_at=str(run["created_at"]),
            updated_at=str(run["updated_at"]),
            plan=AgentPlan(goal=plan["goal"], steps=plan["steps"]) if plan else None,
            stages=[
                AgentStage(
                    agent=step["agent"],
                    attempt=step["attempt"],
                    status=step["status"],
                    duration_ms=max(int(step.get("duration_ms") or 0), 0),
                    error_code=(step.get("error") or {}).get("code"),
                    error_message=(step.get("error") or {}).get("message"),
                    tools=[
                        ToolTrace.model_validate(trace)
                        for trace in step.get("tools") or []
                    ],
                )
                for step in _steps(run)
            ],
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
            budget_id=draft.get("budget_id") if draft else None,
            grounded=is_grounded(run, budget.budget_id),
            overview=overview if isinstance(overview, str) else None,
            findings=[
                item
                for item in (draft or {}).get("findings") or []
                if isinstance(item, str)
            ],
            actions=actions,
            human=AgentHumanDecision(
                decision=human["decision"],
                reviewer=human["reviewer"],
                notes=human.get("notes"),
                decided_at=str(human["decided_at"]),
            )
            if human
            else None,
            error=run.get("error"),
            history=[
                AgentHistoryEvent(
                    sequence=event["sequence"],
                    at=str(event["at"]),
                    actor=event["actor"],
                    event=event["event"],
                )
                for event in history or []
            ],
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise bad_gateway("multi_agent", "run did not match the contract") from exc


def review_body(run: dict[str, Any], decision: AgentReviewRequest) -> dict[str, Any]:
    proposed = run.get("proposed_actions") or []
    accepted = list(dict.fromkeys(decision.accepted))
    if any(
        index >= len(proposed) for index in [*accepted, *decision.corrected_allocations]
    ):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "One or more fields failed validation.",
            [
                {
                    "field": "accepted",
                    "issue": f"must index the run's {len(proposed)} proposed change(s)",
                }
            ],
        )
    body: dict[str, Any] = {
        "decision": decision.decision,
        "reviewer": decision.reviewer,
    }
    if decision.notes:
        body["notes"] = decision.notes
    if decision.decision == "reject":
        return body

    result = run.get("result")
    keep_all = len(accepted) == len(proposed)
    edits = {
        index: amount
        for index, amount in decision.corrected_allocations.items()
        if index in accepted
        and isinstance(proposed[index], dict)
        and amount != proposed[index].get("new_allocation")
    }
    if decision.decision == "approve" and not edits:
        if keep_all:
            return body
        if accepted:
            return body | {"decision": "partial", "accepted_actions": sorted(accepted)}

    if not isinstance(result, dict):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "One or more fields failed validation.",
            [{"field": "decision", "issue": "the run has no answer to correct"}],
        )
    if (
        decision.decision == "correct"
        and not decision.corrected_overview
        and keep_all
        and not edits
    ):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "One or more fields failed validation.",
            [
                {
                    "field": "corrected_overview",
                    "issue": "give a corrected answer, amount or unticked change",
                }
            ],
        )
    corrected = dict(result)
    if decision.corrected_overview:
        corrected["overview"] = decision.corrected_overview
    corrected["actions"] = [
        proposed[index] | {"new_allocation": edits[index]}
        if index in edits
        else proposed[index]
        for index in sorted(accepted)
    ]
    return body | {"decision": "correct", "corrected_result": corrected}


def allocation_changes(run: dict[str, Any]) -> dict[str, Decimal]:
    changes: dict[str, Decimal] = {}
    for item in run.get("approved_actions") or []:
        action = BudgetAgentAction.model_validate(item)
        changes[f"{action.category}_budget"] = Decimal(action.new_allocation)
    return changes
