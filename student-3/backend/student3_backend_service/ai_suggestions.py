"""Prompt assembly and grounding checks for transport recommendations.

The model is only ever shown a bounded candidate list, and anything it names
that was not in that list is rejected rather than shown to a traveller. That
guard is the reason a hallucinated identifier cannot reach the UI.
"""

from __future__ import annotations

import json
import re
from importlib import resources

from .config import Settings
from .errors import ApiError, bad_gateway
from .models import (
    AvailabilityStatus,
    RecommendedTransport,
    TransportOptionRecord,
    TransportRecommendationDraft,
    TransportRecommendationRequest,
    TransportRecommendationResponse,
    TripTransportSummary,
)

PROMPT_ASSET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$")
PROMPT_PACKAGE = "student3_backend_service"

_AI_FIELD = "ai_mode"

# Options a traveller cannot act on are not worth spending prompt budget on,
# and the prompt forbids recommending them anyway.
UNSUITABLE_STATUSES = frozenset(
    {AvailabilityStatus.SOLD_OUT, AvailabilityStatus.CANCELLED},
)


def select_candidates(
    options: list[TransportOptionRecord],
    limit: int,
) -> list[TransportOptionRecord]:
    """The bounded, actionable slice of the catalogue shown to the model.

    Sorted cheapest first so that when the list is truncated the traveller still
    sees the options most likely to matter.
    """
    usable = [
        option
        for option in options
        if option.availability_status not in UNSUITABLE_STATUSES
        and option.seats_remaining > 0
    ]
    usable.sort(key=lambda option: (option.price, option.departure_time, option.id))
    return usable[:limit]


def _candidate_payload(option: TransportOptionRecord) -> dict[str, object]:
    return {
        "transport_id": option.id,
        "type": option.type.value,
        "provider": option.provider,
        "origin": option.origin,
        "destination": option.destination,
        "departure_time": option.departure_time,
        "arrival_time": option.arrival_time,
        "duration_minutes": option.duration_minutes,
        "price": option.price,
        "capacity": option.capacity,
        "seats_remaining": option.seats_remaining,
        "availability_status": option.availability_status.value,
        "notes": option.notes,
    }


def build_prompt(
    settings: Settings,
    request: TransportRecommendationRequest,
    candidates: list[TransportOptionRecord],
    trip_plan: TripTransportSummary | None,
) -> str:
    if PROMPT_ASSET_PATTERN.fullmatch(settings.ai_prompt_asset) is None:
        message = "STUDENT3_BACKEND_AI_PROMPT_ASSET must name a markdown file."
        raise ValueError(message)

    template = (
        resources.files(PROMPT_PACKAGE)
        .joinpath("prompts", settings.ai_prompt_asset)
        .read_text(encoding="utf-8")
    )

    context: dict[str, object] = {
        "currency": settings.currency,
        "question": request.question,
        "requested_route": {
            "origin": request.origin,
            "destination": request.destination,
        },
        "candidates": [_candidate_payload(option) for option in candidates],
    }
    if trip_plan is not None:
        context["already_planned"] = [
            {
                "transport_id": planned.option.id,
                "route": f"{planned.option.origin} to {planned.option.destination}",
                "plan_state": planned.entry.booking_status.value,
            }
            for planned in trip_plan.planned
        ]
        context["trip_id"] = trip_plan.trip_id

    key_facts = [
        f"Currency: {settings.currency}",
        f"Candidate options supplied: {len(candidates)}",
        f"User question: {request.question}",
    ]
    if request.origin or request.destination:
        key_facts.append(
            f"Requested route: {request.origin or 'any'} to "
            f"{request.destination or 'any'}",
        )
    if trip_plan is not None:
        key_facts.append(
            f"Trip {trip_plan.trip_id} already has "
            f"{trip_plan.active_entry_count} active transport entries totalling "
            f"{settings.currency} {trip_plan.estimated_cost_total:.2f}",
        )
    key_facts.append(
        "Only these transport ids may be recommended: "
        + (", ".join(option.id for option in candidates) or "none"),
    )

    prompt = template.replace("{{KEY_FACTS}}", "\n".join(key_facts)).replace(
        "{{TRANSPORT_CONTEXT_JSON}}",
        json.dumps(context, separators=(",", ":"), sort_keys=True),
    )

    if len(prompt) > settings.ai_prompt_max_chars:
        raise ApiError(
            status_code=422,
            code="PROMPT_BUDGET_EXCEEDED",
            message="There is too much transport context for one AI request.",
            details=[
                {
                    "field": _AI_FIELD,
                    "issue": "rendered prompt exceeds the configured limit",
                },
            ],
        )

    return prompt


def resolve_draft(
    draft: TransportRecommendationDraft,
    candidates: list[TransportOptionRecord],
    *,
    run_id: str,
    model: str,
    provider: str,
) -> TransportRecommendationResponse:
    """Turn suggested ids back into real records, refusing anything invented.

    A model that names an id it was not given has failed the one rule that
    matters here, so the whole draft is rejected. Showing a traveller a
    suggestion that cannot be resolved to a real option would be worse than
    showing them an error.
    """
    by_id = {option.id: option for option in candidates}
    resolved: list[RecommendedTransport] = []
    seen: set[str] = set()

    for suggestion in draft.suggestions:
        option = by_id.get(suggestion.transport_id)
        if option is None:
            raise bad_gateway(
                "The AI suggested a transport option that was not offered.",
                [
                    {
                        "field": _AI_FIELD,
                        "issue": (
                            f"unknown transport id {suggestion.transport_id!r}"
                        ),
                    },
                ],
            )

        # A duplicate is not worth failing the whole draft over; it is just
        # noise, so the first mention wins.
        if option.id in seen:
            continue

        seen.add(option.id)
        resolved.append(
            RecommendedTransport(reason=suggestion.reason, option=option),
        )

    if not resolved:
        raise bad_gateway(
            "The AI returned no usable transport suggestions.",
            [{"field": _AI_FIELD, "issue": "no suggestions could be resolved"}],
        )

    return TransportRecommendationResponse(
        overview=draft.overview,
        recommended=resolved,
        considerations=list(draft.considerations),
        disclaimer=draft.disclaimer,
        run_id=run_id,
        model=model,
        provider=provider,
    )
