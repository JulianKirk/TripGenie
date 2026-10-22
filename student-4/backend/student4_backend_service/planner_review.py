"""Grounding, approval validation and explicit itinerary additions for Smart Planner."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import HTTPException
from pydantic import ValidationError

from .activity_routes import get as get_activity
from .assistant import _activity_ids
from .assistant_models import ActivityPart, FinalAction, ToolTrace
from .planner_models import (
    Decision,
    PlannerResponse,
    PlannerSelection,
    Regenerate,
    Run,
    SavedSelection,
    SaveError,
    SuggestionDecision,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .dependencies import DbDep, ItineraryDep, LocationDep


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


def _card_ids(action: FinalAction) -> set[UUID]:
    return {part.activity_id for part in action.parts if isinstance(part, ActivityPart)}


def _accepted(run: Run, payload: Decision) -> FinalAction:
    try:
        original = _validate_result(run.result, run)
        if payload.decision == "correct":
            if payload.corrected_result is None:
                msg = "A corrected result is required."
                raise ValueError(msg)
            action = _validate_result(
                payload.corrected_result.model_dump(mode="json"), run
            )
        else:
            action = original
        if not _card_ids(action) <= _card_ids(original):
            msg = "Only original suggestions can be selected."
            raise ValueError(msg)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            400,
            (
                "Only valid original recommendations backed by this run "
                "activity tool results can be accepted."
            ),
        ) from exc
    selected = {item.activity_id for item in payload.selections or []}
    cards = _card_ids(action)
    if cards and not selected:
        raise HTTPException(
            400,
            (
                "Select at least one suggestion to add to a trip, or reject "
                "and regenerate."
            ),
        )
    if not selected <= cards:
        raise HTTPException(
            400, "Only suggestions retained in the reviewed answer can be added."
        )
    return FinalAction(
        type="final",
        parts=[
            part
            for part in action.parts
            if not isinstance(part, ActivityPart) or part.activity_id in selected
        ],
    )


async def _preflight(
    run: Run,
    payload: Decision,
    itinerary: ItineraryDep,
    db: DbDep,
    location: LocationDep,
) -> tuple[str | None, set[str]]:
    selections = payload.selections or []
    trip_id = payload.trip_id or run.trip_id
    if not selections:
        return trip_id, set()
    if trip_id is None:
        raise HTTPException(400, "Choose a trip for the selected suggestions.")
    trips = await itinerary.list_itineraries()
    trip = next((trip for trip in trips if trip.id == trip_id), None)
    if trip is None:
        raise HTTPException(404, "The selected trip no longer exists.")
    for item in selections:
        if item.date is not None and not trip.start_date <= item.date <= trip.end_date:
            raise HTTPException(
                400, "Activity dates must be within the selected trip dates."
            )
        activity = await get_activity(item.activity_id, db=db, location=location)
        if not activity.is_active:
            raise HTTPException(400, "An inactive activity cannot be added to a trip.")
    existing = await itinerary.activities_in(trip_id)
    return trip_id, {row.activity_id for row in existing}


async def _save(
    response: PlannerResponse,
    selections: list[PlannerSelection],
    trip_id: str,
    existing: set[str],
    itinerary: ItineraryDep,
    *,
    update_existing: bool = False,
) -> None:
    for item in selections:
        if str(item.activity_id) in existing and not update_existing:
            response.saved.append(
                SavedSelection(
                    activity_id=item.activity_id,
                    trip_id=trip_id,
                    status="already_present",
                )
            )
            continue
        try:
            await itinerary.add(
                item.activity_id,
                trip_id,
                item.date.isoformat() if item.date else None,
                item.start_time.strftime("%H:%M") if item.start_time else None,
            )
            response.saved.append(
                SavedSelection(
                    activity_id=item.activity_id,
                    trip_id=trip_id,
                    status="updated" if str(item.activity_id) in existing else "added",
                )
            )
        except HTTPException:
            response.save_errors.append(
                SaveError(
                    activity_id=item.activity_id,
                    trip_id=trip_id,
                    message=(
                        "Could not confirm this activity was added. Check the trip "
                        "before trying again; it may have been saved."
                    ),
                )
            )


def _confirm_approval(updated: Run, action: FinalAction, decision: str) -> None:
    if (
        updated.status != "completed"
        or updated.human is None
        or updated.human.decision != decision
    ):
        raise HTTPException(
            502,
            (
                "Smart Planner did not confirm approval. No itinerary "
                "additions were attempted."
            ),
        )
    try:
        confirmed = _validate_result(updated.final_result, updated)
        if confirmed != action:
            msg = "Different approved result"
            raise ValueError(msg)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            502,
            (
                "Smart Planner returned another approved result. No "
                "itinerary additions were attempted."
            ),
        ) from exc


def _rejected_ids(run: Run, payload: Regenerate) -> list[str]:
    try:
        original = _validate_result(run.result, run)
    except (ValueError, ValidationError):
        if payload.dismissed_activity_ids:
            raise HTTPException(
                400, "Only grounded suggestions from this result can be dismissed."
            ) from None
        return []
    if not set(payload.dismissed_activity_ids) <= _card_ids(original):
        raise HTTPException(400, "Only suggestions from this result can be dismissed.")
    return sorted(str(key) for key in _card_ids(original))


def _audit_row(
    row: SuggestionDecision,
    selection: PlannerSelection | None,
    default_trip: str | None,
) -> list[object]:
    result: list[object] = [str(row.activity_id), row.decision, row.notes]
    if row.decision == "approve":
        if selection is None:
            raise HTTPException(
                400, "An approved suggestion needs an itinerary selection."
            )
        trip_id = selection.trip_id or default_trip
        if (
            not trip_id
            or row.trip_id != trip_id
            or row.date is None
            or row.start_time is None
        ):
            raise HTTPException(
                400, "Choose a trip, date and start time for each approval."
            )
        if row.date != selection.date or row.start_time != selection.start_time:
            raise HTTPException(
                400, "Approval schedules must match the selected additions."
            )
        result.extend([trip_id, row.date.isoformat(), row.start_time.strftime("%H:%M")])
    elif row.trip_id is not None or row.date is not None or row.start_time is not None:
        raise HTTPException(
            400, "Rejected suggestions cannot contain itinerary additions."
        )
    return result


def _item_audit(run: Run, payload: Decision) -> str | None:
    """Validate a complete staged choice set and fit the shared review contract."""
    if payload.item_decisions is None:
        return payload.notes
    try:
        original = _validate_result(run.result, run)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            400, "Only grounded original suggestions can be reviewed."
        ) from exc
    rows = payload.item_decisions
    ids = [row.activity_id for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != _card_ids(original):
        raise HTTPException(400, "Record one decision for every original suggestion.")
    approved = {row.activity_id for row in rows if row.decision == "approve"}
    selected = {row.activity_id for row in payload.selections or []}
    if selected != approved:
        raise HTTPException(
            400, "Selected additions must match the approved suggestions."
        )
    if (
        payload.decision != ("approve" if approved else "reject")
        or payload.corrected_result is not None
    ):
        raise HTTPException(
            400, "The overall decision must match the suggestion choices."
        )
    selections = {item.activity_id: item for item in payload.selections or []}
    data: dict[str, object] = {
        "activity_reviews": [
            _audit_row(
                row, selections.get(row.activity_id), payload.trip_id or run.trip_id
            )
            for row in rows
        ]
    }
    if payload.notes:
        data["notes"] = payload.notes
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 1000:
        raise HTTPException(
            400,
            (
                "Review reasons are too long to record together. "
                "Shorten the reasons and apply again."
            ),
        )
    return encoded


def _recorded_choices(run: Run) -> list[SuggestionDecision]:
    if run.human is None or not run.human.notes:
        return []
    try:
        data = json.loads(run.human.notes)
        if not isinstance(data, dict) or not isinstance(
            data.get("activity_reviews"), list
        ):
            return []
        rows = data["activity_reviews"]
        if any(not isinstance(row, list) or len(row) not in {3, 6} for row in rows):
            return []
        result = [
            SuggestionDecision.model_validate(
                {
                    "activity_id": row[0],
                    "decision": row[1],
                    "notes": row[2],
                    **(
                        {"trip_id": row[3], "date": row[4], "start_time": row[5]}
                        if len(row) == 6
                        else {}
                    ),
                }
            )
            for row in rows
        ]
        original = _validate_result(run.result, run)
        if len(result) != len({row.activity_id for row in result}) or {
            row.activity_id for row in result
        } != _card_ids(original):
            return []
        approved = {row.activity_id for row in result if row.decision == "approve"}
        if run.status == "completed":
            final = _validate_result(run.final_result, run)
            if _card_ids(final) != approved:
                return []
        elif run.status != "rejected" or approved:
            return []
        return result
    except (ValueError, ValidationError):
        return []


def _confirm_item_audit(run: Run, payload: Decision, notes: str | None) -> None:
    if payload.item_decisions is None:
        return
    if (
        run.human is None
        or run.human.notes != notes
        or _recorded_choices(run) != payload.item_decisions
    ):
        raise HTTPException(
            502,
            "Smart Planner did not confirm the complete suggestion review audit. "
            "No itinerary additions were attempted.",
        )


async def _preflight_groups(
    run: Run,
    payload: Decision,
    itinerary: ItineraryDep,
    db: DbDep,
    location: LocationDep,
) -> list[tuple[list[PlannerSelection], str, set[str]]]:
    groups: dict[str, list[PlannerSelection]] = {}
    for item in payload.selections or []:
        trip_id = item.trip_id or payload.trip_id or run.trip_id
        if trip_id is None:
            raise HTTPException(
                400, "Choose an itinerary for each approved suggestion."
            )
        groups.setdefault(trip_id, []).append(item)
    validated = []
    for trip_id, selections in groups.items():
        grouped = payload.model_copy(
            update={"trip_id": trip_id, "selections": selections}
        )
        _, existing = await _preflight(run, grouped, itinerary, db, location)
        validated.append((selections, trip_id, existing))
    return validated
