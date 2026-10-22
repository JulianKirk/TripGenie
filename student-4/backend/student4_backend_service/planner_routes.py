"""Feature-owned recommendations and explicit human-approved itinerary changes."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .activity_routes import get as get_activity
from .assistant import _prompt_asset
from .assistant_models import (
    ActivityPart,
    AssistantRequest,
    AssistantResponse,
    FinalAction,
)
from .dependencies import (  # noqa: TC001 - FastAPI annotations
    DbDep,
    ItineraryDep,
    LocationDep,
)
from .planner_client import PlannerClient
from .planner_models import (
    Decision,
    Evidence,
    HistoryEvent,
    PlannerResponse,
    PlannerSelection,
    Regenerate,
    Run,
    RunId,
)
from .planner_review import (
    _accepted,
    _confirm_approval,
    _confirm_item_audit,
    _item_audit,
    _preflight_groups,
    _recorded_choices,
    _rejected_ids,
    _save,
    _tools,
    _validate_result,
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


async def _present(run: Run, resolve: ActivityLookup) -> PlannerResponse:
    answer = AssistantResponse(request_id=run.run_id, tools=_tools(run))
    choices = _recorded_choices(run)
    data = run.final_result if run.status == "completed" and not choices else run.result
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
    return PlannerResponse(run=run, answer=answer, item_decisions=choices)


@router.post("", status_code=202, response_model=PlannerResponse)
async def start(
    payload: AssistantRequest, client: PlannerDep, db: DbDep, location: LocationDep
) -> PlannerResponse:
    body = _start_body(payload)
    run = _run(await client.request("POST", "/runs", body))
    return await _present(run, partial(get_activity, db=db, location=location))


def _start_body(payload: AssistantRequest) -> dict[str, object]:
    body: dict[str, object] = {
        "feature": "student-4",
        "task": payload.question,
        "feature_instructions": _prompt_asset("activity_planner_rules_v1.md"),
        "worker_system": _prompt_asset("activity_planner_v1.md"),
        "output_schema": FinalAction.model_json_schema(),
        "allowed_tools": TOOLS,
        "grounding": {"source": "student-4", "id_paths": ["parts[].activity_id"]},
        "correlation_id": f"student4-plan-{uuid4().hex[:16]}",
        "metadata": {"service": "student-4-backend"},
    }
    if payload.trip_id:
        body["trip_id"] = payload.trip_id
    return body


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
    itinerary: ItineraryDep,
) -> PlannerResponse:
    run = _run(await client.request("GET", f"/runs/{run_id}"), run_id)
    if run.status != "awaiting_human":
        raise HTTPException(
            409, "This run is no longer awaiting review. Refresh its status."
        )
    body: dict[str, object] = {
        "decision": payload.decision,
        "reviewer": payload.reviewer,
    }
    notes = _item_audit(run, payload)
    if notes is not None:
        body["notes"] = notes
    action: FinalAction | None = None
    additions: list[tuple[list[PlannerSelection], str, set[str]]] = []
    if payload.decision != "reject":
        if any(check.blocking and not check.passed for check in run.checks):
            raise HTTPException(
                400,
                "This run has failed checks. Reject it and start a revised request.",
            )
        action = _accepted(run, payload)
        additions = await _preflight_groups(run, payload, itinerary, db, location)
        if (
            payload.decision == "correct"
            or action.model_dump(mode="json") != run.result
        ):
            body["decision"] = "correct"
            body["corrected_result"] = action.model_dump(mode="json")
    updated = _run(await client.request("POST", f"/runs/{run_id}/review", body), run_id)
    _confirm_item_audit(updated, payload, notes)
    if action is not None:
        _confirm_approval(updated, action, str(body["decision"]))
    response = await _present(updated, partial(get_activity, db=db, location=location))
    if action is not None:
        for selections, trip_id, existing in additions:
            await _save(
                response,
                selections,
                trip_id,
                existing,
                itinerary,
                update_existing=payload.item_decisions is not None,
            )
    return response


@router.post("/{run_id}/regenerate", status_code=202, response_model=PlannerResponse)
async def regenerate(
    run_id: RunId,
    payload: Regenerate,
    client: PlannerDep,
    db: DbDep,
    location: LocationDep,
) -> PlannerResponse:
    run = _run(await client.request("GET", f"/runs/{run_id}"), run_id)
    if run.status != "awaiting_human":
        raise HTTPException(
            409, "This run is no longer awaiting review. Refresh its status."
        )
    try:
        request = AssistantRequest(question=run.task, trip_id=run.trip_id)
    except ValidationError as exc:
        raise HTTPException(
            400, "This run cannot be regenerated. Start a new search."
        ) from exc
    rejected_ids = _rejected_ids(run, payload)
    rejected = _run(
        await client.request(
            "POST",
            f"/runs/{run_id}/review",
            {
                "decision": "reject",
                "reviewer": payload.reviewer,
                "notes": payload.feedback,
            },
        ),
        run_id,
    )
    if rejected.status != "rejected":
        raise HTTPException(
            502, "Smart Planner did not confirm rejection. No new search was started."
        )
    body = _start_body(request)
    body["context"] = {
        "human_feedback": payload.feedback,
        "previous_run_id": run_id,
        "rejected_activity_ids": rejected_ids,
    }
    body["metadata"] = {"service": "student-4-backend", "parent_run_id": run_id}
    try:
        started = _run(await client.request("POST", "/runs", body))
    except HTTPException as exc:
        raise HTTPException(
            exc.status_code,
            (
                "The previous result was rejected, but a replacement run "
                "could not be confirmed. Do not resubmit automatically; "
                "a new run may have started."
            ),
        ) from exc
    response = await _present(started, partial(get_activity, db=db, location=location))
    response.previous_run_id = run_id
    return response


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
    return Evidence(run=run, history=events, item_decisions=_recorded_choices(run))
