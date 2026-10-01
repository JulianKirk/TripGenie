"""Prompt assembly and grounding checks for transport recommendations.

Release 1: the model looks transport up itself through the shared MCP tools
that AI-Mode offers on every `/generate` call, instead of being handed a
candidate list. The grounding guard moves with it. A suggestion is accepted
only if its id came back in a successful Student 3 tool result during the
same run, and it is then re-read from this service so the traveller sees the
stored record, not the model's copy of it. An id the model never retrieved is
rejected rather than shown, which is why a hallucinated identifier still
cannot reach the UI.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from importlib import resources
from typing import Any

from .config import Settings
from .errors import ApiError, bad_gateway
from .models import (
    AvailabilityStatus,
    RecommendedTransport,
    ToolCallTrace,
    TransportOptionRecord,
    TransportRecommendationDraft,
    TransportRecommendationRequest,
    TransportRecommendationResponse,
)

PROMPT_ASSET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$")
PROMPT_PACKAGE = "student3_backend_service"
TRANSPORT_SOURCE = "student-3"
# The MCP server caps a transport search at 50 results.
MAX_SEARCH_LIMIT = 50

_AI_FIELD = "ai_mode"

# Options a traveller cannot act on must never be recommended, even when a
# tool returned them.
UNSUITABLE_STATUSES = frozenset(
    {AvailabilityStatus.SOLD_OUT, AvailabilityStatus.CANCELLED},
)

OptionLookup = Callable[[str], TransportOptionRecord | None]


def is_actionable(option: TransportOptionRecord) -> bool:
    """Whether a traveller could still plan this option.

    A seat count of None means the itinerary service could not be reached, so
    the figure is unknown rather than zero; the operator-declared status still
    excludes anything a traveller could not take.
    """
    return option.availability_status not in UNSUITABLE_STATUSES and (
        option.seats_remaining is None or option.seats_remaining > 0
    )


def build_prompt(
    settings: Settings,
    request: TransportRecommendationRequest,
) -> tuple[str, str]:
    """The system prompt (a versioned asset) and the user message (JSON data).

    Nothing from the catalogue is pre-loaded: the model has to fetch it.
    """
    if PROMPT_ASSET_PATTERN.fullmatch(settings.ai_prompt_asset) is None:
        message = "STUDENT3_BACKEND_AI_PROMPT_ASSET must name a markdown file."
        raise ValueError(message)

    template = (
        resources.files(PROMPT_PACKAGE)
        .joinpath("prompts", settings.ai_prompt_asset)
        .read_text(encoding="utf-8")
    )
    system = template.replace("{{CURRENCY}}", settings.currency)

    # The first search is spelled out so a small model does not have to guess
    # which filters it has; every later call is the model's own choice.
    search_limit = min(settings.ai_max_candidates, MAX_SEARCH_LIMIT)
    first_search: dict[str, object] = {"limit": search_limit}
    for field in ("origin", "destination"):
        value = getattr(request, field)
        if value is not None:
            first_search[field] = value
    user: dict[str, object] = {
        "question": request.question,
        "first_search": first_search,
    }
    if request.trip_id is not None:
        user["trip_id"] = request.trip_id
    prompt = json.dumps(user, separators=(",", ":"), sort_keys=True)

    if len(system) + len(prompt) > settings.ai_prompt_max_chars:
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

    return system, prompt


def _transport_ids(trace: dict[str, Any]) -> list[str]:
    """Student 3 record ids in one successful tool result, in result order."""
    if trace.get("status") != "success" or not isinstance(trace.get("result"), dict):
        return []
    envelope = trace["result"].get("structuredContent")
    if (
        not isinstance(envelope, dict)
        or envelope.get("ok") is not True
        or envelope.get("source") != TRANSPORT_SOURCE
        or not isinstance(envelope.get("data"), dict)
    ):
        return []

    data = envelope["data"]
    rows: list[Any] = []
    if isinstance(data.get("items"), list):  # search and compare
        rows = data["items"]
    elif isinstance(data.get("planned"), list):  # trip costs
        rows = [
            item.get("option") for item in data["planned"] if isinstance(item, dict)
        ]
    elif "id" in data:  # a single option
        rows = [data]

    return [
        row["id"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def summarise_tools(traces: list[dict[str, Any]]) -> list[ToolCallTrace]:
    """AI-Mode's tool trace, kept for display and stripped to what it shows."""
    summary: list[ToolCallTrace] = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        status = trace.get("status")
        result = trace.get("result")
        summary.append(
            ToolCallTrace(
                tool=str(trace.get("tool", "unknown")),
                arguments=trace.get("arguments")
                if isinstance(trace.get("arguments"), dict)
                else {},
                status=status if status in {"success", "rejected"} else "error",
                duration_ms=max(int(trace.get("duration_ms") or 0), 0),
                error=str(trace["error"]) if trace.get("error") else None,
                transport_ids=_transport_ids(trace),
                result=result.get("structuredContent")
                if isinstance(result, dict)
                and isinstance(result.get("structuredContent"), dict)
                else None,
            ),
        )
    return summary


def resolve_draft(
    draft: TransportRecommendationDraft,
    tools: list[ToolCallTrace],
    lookup: OptionLookup,
    *,
    run_id: str,
    model: str,
    provider: str,
) -> TransportRecommendationResponse:
    """Turn suggested ids back into real records, refusing anything ungrounded.

    A model that names an id no tool returned has failed the one rule that
    matters here, so the whole draft is rejected. A grounded option that can
    no longer be planned is dropped and named instead of shown. A draft with
    no suggestions is the model saying nothing suitable was found.
    """
    grounded = {transport_id for trace in tools for transport_id in trace.transport_ids}
    resolved: list[RecommendedTransport] = []
    unavailable: list[str] = []
    seen: set[str] = set()

    for suggestion in draft.suggestions:
        transport_id = suggestion.transport_id
        if transport_id not in grounded:
            raise bad_gateway(
                "The AI suggested a transport option it did not look up.",
                [
                    {
                        "field": _AI_FIELD,
                        "issue": (
                            f"ungrounded transport id {transport_id!r}: no "
                            "transport tool returned it"
                        ),
                    },
                ],
            )

        # A duplicate is not worth failing the whole draft over; it is just
        # noise, so the first mention wins.
        if transport_id in seen:
            continue
        seen.add(transport_id)

        option = lookup(transport_id)
        if option is None or not is_actionable(option):
            unavailable.append(transport_id)
            continue

        resolved.append(RecommendedTransport(reason=suggestion.reason, option=option))

    # No suggestions at all is an honest "nothing found", answered by the
    # overview. Suggestions that all turned out unusable are a failure.
    if draft.suggestions and not resolved:
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
        tools=tools,
        unavailable_transport_ids=unavailable,
    )
