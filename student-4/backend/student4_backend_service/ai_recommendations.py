from __future__ import annotations

import asyncio
import json
import re
from importlib import resources
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import ValidationError

from .activity_routes import _public_activity, _query
from .prompt_filters import apply_explicit_filters
from .schemas import (
    Activity,
    ActivityEvaluationDraft,
    ActivityQuery,
    ActivitySearchPlanDraft,
    ActivitySummary,
    ItineraryTrip,
    RecommendationEvaluationRequest,
    RecommendationEvaluationResponse,
    RecommendationPlan,
    RecommendationPlanRequest,
    RecommendedActivity,
    TripActivityWire,
)

if TYPE_CHECKING:
    from .ai_mode_client import AiModeClient
    from .client import DatabaseClient
    from .config import Settings
    from .itinerary_client import ItineraryClient
    from .location_client import LocationClient

PROMPT_ASSET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$")
PROMPT_PACKAGE = "student4_backend_service"


def _prompt_asset(name: str) -> str:
    if PROMPT_ASSET_PATTERN.fullmatch(name) is None:
        message = "AI prompt assets must name a markdown file."
        raise ValueError(message)
    return (
        resources.files(PROMPT_PACKAGE)
        .joinpath("prompts", name)
        .read_text(encoding="utf-8")
    )


async def _trip_context(
    trip_id: str | None,
    itinerary: ItineraryClient,
) -> tuple[ItineraryTrip | None, list[TripActivityWire]]:
    if trip_id is None:
        return None, []
    trips = await itinerary.list_itineraries()
    trip = next((item for item in trips if item.id == trip_id), None)
    if trip is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown trip")
    return trip, await itinerary.activities_in(trip_id)


def _plan_schema() -> dict[str, Any]:
    schema = ActivitySearchPlanDraft.model_json_schema()
    query = schema["$defs"]["ActivityQuery"]["properties"]
    for field in ("sort", "include_inactive", "limit", "offset"):
        query.pop(field, None)
    location = schema["$defs"]["LocationFilter"]["properties"]
    location.pop("street", None)
    return schema


def _trip_summary(summary: str, trip: ItineraryTrip) -> str:
    base = summary.strip().rstrip(".")
    if base.casefold() == "no filters applied":
        base = "activities"
    return (
        f"{base} for {trip.name} in {trip.destination} "
        f"({trip.traveller_count} travellers)"
    )


async def _generate_plan_draft(
    prompt: str,
    *,
    ai: AiModeClient,
    settings: Settings,
) -> ActivitySearchPlanDraft:
    last_error: ValueError | ValidationError | None = None
    for output_attempt in (1, 2):
        attempt_prompt = prompt
        if output_attempt == 2:
            attempt_prompt += (
                "\nYour previous answer could not be used. Start again and return "
                "only JSON matching the supplied schema."
            )
        generated = await ai.generate(
            prompt=attempt_prompt,
            schema=_plan_schema(),
            correlation_id=f"student4-plan-{uuid4().hex[:16]}",
            metadata={
                "service": settings.service_name,
                "feature": "activity-search-plan",
                "output_attempt": str(output_attempt),
            },
        )
        try:
            return ActivitySearchPlanDraft.model_validate_json(generated.response)
        except (ValueError, ValidationError) as exc:
            last_error = exc
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "The AI returned an unusable activity search.",
    ) from last_error


async def plan_search(
    payload: RecommendationPlanRequest,
    *,
    ai: AiModeClient,
    location: LocationClient,
    itinerary: ItineraryClient,
    settings: Settings,
) -> RecommendationPlan:
    trip, existing = await _trip_context(payload.trip_id, itinerary)
    countries, cities = await location.vocabulary()
    context: dict[str, object] = {
        "question": payload.question,
        "known_countries": countries,
        "known_cities": cities,
    }
    if trip is not None:
        context["trip"] = trip.model_dump(mode="json")
        context["existing_itinerary_activities"] = [
            row.model_dump(mode="json") for row in existing
        ]
    prompt = _prompt_asset(settings.ai_plan_prompt_asset).replace(
        "{{CONTEXT_JSON}}",
        json.dumps(context, separators=(",", ":"), sort_keys=True),
    )
    if len(prompt) > settings.ai_prompt_max_chars:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "There is too much context for one AI request.",
        )
    draft = await _generate_plan_draft(prompt, ai=ai, settings=settings)

    destination = (
        await location.destination_filter(trip.destination)
        if trip is not None
        else None
    )
    query_seed = draft.query.model_dump(mode="json", exclude_none=True)
    if destination is not None:
        query_seed["location"] = destination
    query_body, recovered_filters = apply_explicit_filters(
        payload.question,
        query_seed,
        implicit_date=(
            trip.start_date.isoformat()
            if trip is not None and trip.start_date == trip.end_date
            else None
        ),
    )
    query_body.update(
        sort="NAME_ASC",
        include_inactive=False,
        limit=min(settings.ai_max_candidates, 20),
        offset=0,
    )
    if trip is not None:
        if destination is not None:
            query_body["location"] = destination
        query_body["party_size"] = trip.traveller_count
        availability = query_body.get("availability")
        if isinstance(availability, dict) and not (
            trip.start_date.isoformat()
            <= str(availability.get("date", ""))
            <= trip.end_date.isoformat()
        ):
            query_body.pop("availability")

    summary = draft.summary
    if summary.strip().rstrip(".").casefold() == "no filters applied":
        summary = (
            payload.question.strip().rstrip(".") if recovered_filters else "activities"
        )
    if trip is not None:
        summary = _trip_summary(summary, trip)

    return RecommendationPlan(
        question=payload.question,
        trip_id=payload.trip_id,
        query=query_body,
        summary=summary,
        trip_context_available=trip is not None,
    )


async def _enforced_query(
    query: ActivityQuery,
    *,
    trip: ItineraryTrip | None,
    location: LocationClient,
    settings: Settings,
) -> ActivityQuery:
    body = query.model_dump(mode="json", exclude_none=True)
    body.update(
        sort="NAME_ASC",
        include_inactive=False,
        limit=min(settings.ai_max_candidates, 20),
        offset=0,
    )
    if trip is not None:
        destination = await location.destination_filter(trip.destination)
        if destination is not None:
            body["location"] = destination
        body["party_size"] = trip.traveller_count
        availability = body.get("availability")
        if isinstance(availability, dict) and not (
            trip.start_date.isoformat()
            <= str(availability.get("date", ""))
            <= trip.end_date.isoformat()
        ):
            body.pop("availability")
    return ActivityQuery.model_validate(body)


def _evaluation_schema() -> dict[str, Any]:
    schema = ActivityEvaluationDraft.model_json_schema()
    query = schema["$defs"]["ActivityQuery"]["properties"]
    for field in ("sort", "include_inactive", "limit", "offset"):
        query.pop(field, None)
    schema["$defs"]["LocationFilter"]["properties"].pop("street", None)
    return schema


async def _reject_weakened_trip_constraints(
    query: ActivityQuery,
    *,
    trip: ItineraryTrip | None,
    location: LocationClient,
) -> None:
    if trip is None:
        return
    destination = await location.destination_filter(trip.destination)
    supplied_location = (
        query.location.model_dump(mode="json", exclude_none=True)
        if query.location is not None
        else None
    )
    location_changed = (
        destination is not None
        and "location" in query.model_fields_set
        and supplied_location != destination
    )
    party_changed = (
        "party_size" in query.model_fields_set
        and query.party_size != trip.traveller_count
    )
    if location_changed or party_changed:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The revised search weakened trip constraints.",
        )


async def _hydrate_active_candidates(
    summaries: list[ActivitySummary],
    *,
    db: DatabaseClient,
    location: LocationClient,
) -> list[Activity]:
    records = await asyncio.gather(
        *(db.get(row.id) for row in summaries), return_exceptions=True
    )
    active_records = []
    for record in records:
        if isinstance(record, HTTPException):
            if record.status_code == status.HTTP_404_NOT_FOUND:
                continue
            raise record
        if isinstance(record, BaseException):
            raise record
        if record.is_active:
            active_records.append(record)
    return list(
        await asyncio.gather(
            *(_public_activity(record, location) for record in active_records)
        )
    )


async def evaluate_search(
    payload: RecommendationEvaluationRequest,
    *,
    ai: AiModeClient,
    db: DatabaseClient,
    location: LocationClient,
    itinerary: ItineraryClient,
    settings: Settings,
) -> RecommendationEvaluationResponse:
    trip, existing = await _trip_context(payload.trip_id, itinerary)
    query = await _enforced_query(
        payload.query, trip=trip, location=location, settings=settings
    )
    found = await _query(query, db, location)
    already_selected = {row.activity_id for row in existing}
    summaries = [
        row for row in found.activities if str(row.id) not in already_selected
    ][: settings.ai_max_candidates]
    candidates = await _hydrate_active_candidates(
        summaries,
        db=db,
        location=location,
    )

    context: dict[str, object] = {
        "question": payload.question,
        "attempt": payload.attempt,
        "query_used": query.model_dump(mode="json", exclude_none=True),
        "candidates": [
            activity.model_dump(mode="json", exclude_none=True)
            for activity in candidates
        ],
    }
    if trip is not None:
        context["trip"] = trip.model_dump(mode="json")
        context["existing_itinerary_activities"] = [
            row.model_dump(mode="json") for row in existing
        ]
    prompt = _prompt_asset(settings.ai_evaluation_prompt_asset).replace(
        "{{CONTEXT_JSON}}",
        json.dumps(context, separators=(",", ":"), sort_keys=True),
    )
    if len(prompt) > settings.ai_prompt_max_chars:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "There is too much activity context for one AI request.",
        )
    generated = await ai.generate(
        prompt=prompt,
        schema=_evaluation_schema(),
        correlation_id=f"student4-evaluate-{uuid4().hex[:16]}",
        metadata={
            "service": settings.service_name,
            "feature": "activity-recommendations",
            "candidates": str(len(candidates)),
            "attempt": str(payload.attempt),
        },
    )
    try:
        draft = ActivityEvaluationDraft.model_validate_json(generated.response)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The AI returned unusable activity recommendations.",
        ) from exc

    by_id = {activity.id: activity for activity in candidates}
    recommended: list[RecommendedActivity] = []
    seen: set[object] = set()
    for suggestion in draft.suggestions:
        activity = by_id.get(suggestion.activity_id)
        if activity is None:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "The AI suggested an activity outside the search results.",
            )
        if activity.id in seen:
            continue
        seen.add(activity.id)
        recommended.append(
            RecommendedActivity(reason=suggestion.reason, activity=activity)
        )

    status_value = "complete" if recommended else "no_match"
    response_query = query
    response_summary = payload.summary
    response_attempt = payload.attempt
    revision_explanation = None
    if not recommended and draft.revised_query is not None and payload.attempt == 1:
        await _reject_weakened_trip_constraints(
            draft.revised_query,
            trip=trip,
            location=location,
        )
        revised = await _enforced_query(
            draft.revised_query, trip=trip, location=location, settings=settings
        )
        if revised.model_dump(mode="json") != query.model_dump(mode="json"):
            status_value = "retry"
            response_query = revised
            response_attempt = 2
            revision_explanation = draft.revision_explanation
            response_summary = draft.revised_summary or payload.summary

    return RecommendationEvaluationResponse(
        status=status_value,
        attempt=response_attempt,
        query=response_query,
        summary=response_summary,
        matched_count=found.total,
        evaluated_count=len(candidates),
        recommended=recommended,
        overview=draft.overview,
        considerations=list(draft.considerations),
        disclaimer=draft.disclaimer,
        revision_explanation=revision_explanation,
        run_id=generated.run_id,
        model=generated.model,
        provider=generated.provider,
    )
