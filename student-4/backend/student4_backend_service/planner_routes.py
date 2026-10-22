"""Feature-owned recommendation workflow; no automatic itinerary changes."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .activity_routes import get as get_activity
from .assistant import _activity_ids, _prompt_asset
from .assistant_models import (
    ActivityPart,
    AssistantRequest,
    AssistantResponse,
    FinalAction,
    ToolTrace,
)
from .dependencies import DbDep, LocationDep  # noqa: TC001 - FastAPI annotations
from .planner_client import PlannerClient
from .planner_models import (
    Decision,
    Evidence,
    HistoryEvent,
    PlannerResponse,
    Run,
    RunId,
)

if TYPE_CHECKING:
    from .assistant import ActivityLookup

router = APIRouter(prefix="/activity/planner/runs", tags=["Smart Planner"])
TOOLS = [
    "activities_search",
    "activities_get",
    "activities_list_categories",
    "activities_committed_costs",
    "trip_get_context",
    "trips_list_itinerary_items",
]


def _client(request: Request) -> PlannerClient:
    return cast("PlannerClient", request.app.state.planner)


PlannerDep = Annotated[PlannerClient, Depends(_client)]


def _run(data: object, run_id: str | None = None) -> Run:
    try:
        run = Run.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(502, "Smart Planner returned an invalid run.") from exc
    if run.feature != "student-4":
        raise HTTPException(404, "Smart Planner run not found.")
    if run_id is not None and run.run_id != run_id:
        raise HTTPException(502, "Smart Planner returned another run.")
    return run


def _tools(run: Run) -> list[ToolTrace]:
    return [tool for step in run.steps for tool in step.tools]


def _validate_result(data: object, run: Run) -> FinalAction:
    action = FinalAction.model_validate(data)
    known = set().union(*(_activity_ids(tool) for tool in _tools(run)))
    refs = [str(p.activity_id) for p in action.parts if isinstance(p, ActivityPart)]
    if len(refs) > 6 or any(ref not in known for ref in refs):
        msg = "Ungrounded activity references"
        raise ValueError(msg)
    return action


async def _present(run: Run, resolve: ActivityLookup) -> PlannerResponse:
    answer = AssistantResponse(request_id=run.run_id, tools=_tools(run))
    data = run.final_result if run.status == "completed" else run.result
    if data is not None:
        try:
            action = _validate_result(data, run)
            for part in action.parts:
                if isinstance(part, ActivityPart):
                    key = str(part.activity_id)
                    try:
                        activity = await resolve(UUID(key))
                        if str(activity.id) != key:
                            msg = "Activity lookup returned another ID"
                            raise ValueError(msg)
                        answer.activities[key] = activity
                    except HTTPException:
                        answer.unavailable_activity_ids.append(key)
            answer.parts, answer.status = action.parts, "complete"
        except (ValueError, ValidationError):
            answer.activities = {}
            answer.error = (
                "The proposed answer contains invalid or ungrounded activity "
                "references. Review the tool evidence or reject this run."
            )
    if run.error:
        answer.error = (
            "The planning workflow failed. Review the recorded steps and "
            "tool results for partial execution."
        )
    return PlannerResponse(run=run, answer=answer)


@router.post("", status_code=202, response_model=PlannerResponse)
async def start(
    payload: AssistantRequest, client: PlannerDep, db: DbDep, location: LocationDep
) -> PlannerResponse:
    body: dict[str, object] = {
        "feature": "student-4",
        "task": payload.question,
        "worker_system": _prompt_asset("activity_planner_v1.md"),
        "output_schema": FinalAction.model_json_schema(),
        "allowed_tools": TOOLS,
        "grounding": {"source": "student-4", "id_paths": ["parts[].activity_id"]},
        "correlation_id": f"student4-plan-{uuid4().hex[:16]}",
        "metadata": {"service": "student-4-backend"},
    }
    if payload.trip_id:
        body["trip_id"] = payload.trip_id
    run = _run(await client.request("POST", "/runs", body))
    return await _present(run, partial(get_activity, db=db, location=location))


@router.get("/{run_id}", response_model=PlannerResponse)
async def get(
    run_id: RunId, client: PlannerDep, db: DbDep, location: LocationDep
) -> PlannerResponse:
    run = _run(await client.request("GET", f"/runs/{run_id}"), run_id)
    return await _present(run, partial(get_activity, db=db, location=location))


@router.post("/{run_id}/review", response_model=PlannerResponse)
async def review(
    run_id: RunId,
    payload: Decision,
    client: PlannerDep,
    db: DbDep,
    location: LocationDep,
) -> PlannerResponse:
    run = _run(await client.request("GET", f"/runs/{run_id}"), run_id)
    if run.status != "awaiting_human":
        raise HTTPException(
            409, "This run is no longer awaiting review. Refresh its status."
        )
    if payload.decision != "reject":
        if any(check.blocking and not check.passed for check in run.checks):
            raise HTTPException(
                400,
                "This run has failed checks. Reject it and start a revised request.",
            )
        data = (
            payload.corrected_result.model_dump(mode="json")
            if payload.decision == "correct" and payload.corrected_result is not None
            else run.result
        )
        if payload.decision == "correct" and payload.corrected_result is None:
            raise HTTPException(400, "A corrected result is required.")
        try:
            _validate_result(data, run)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                400,
                (
                    "Only valid recommendations backed by this run activity tool "
                    "results can be accepted."
                ),
            ) from exc
    updated = _run(
        await client.request(
            "POST",
            f"/runs/{run_id}/review",
            payload.model_dump(mode="json", exclude_none=True),
        ),
        run_id,
    )
    return await _present(updated, partial(get_activity, db=db, location=location))


@router.get("/{run_id}/history", response_model=Evidence)
async def history(run_id: RunId, client: PlannerDep) -> Evidence:
    run = _run(await client.request("GET", f"/runs/{run_id}"), run_id)
    data = await client.request("GET", f"/runs/{run_id}/history")
    try:
        if not isinstance(data, list):
            msg = "Expected event list"
            raise ValueError(msg)
        events = [HistoryEvent.model_validate(row) for row in data]
        if any(event.run_id != run_id for event in events):
            msg = "Another run in history"
            raise ValueError(msg)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(502, "Smart Planner returned invalid history.") from exc
    return Evidence(run=run, history=events)
