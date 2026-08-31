from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, time
from typing import Annotated
from uuid import uuid4

from pydantic import Field, StringConstraints, ValidationError, field_validator

from .ai_contract import (
    CORRELATION_ID_PATTERN,
    sanitise_log_value,
    validate_correlation_id_value,
)
from .ai_mode_client import AiModeClient
from .config import AI_MAX_ATTEMPTS_MAX, AI_MAX_ATTEMPTS_MIN, Settings
from .errors import ai_output_invalid, validation_error
from .models import (
    DependencyStatus,
    IsoDate,
    ItineraryCategory,
    ItineraryItemCreate,
    ItineraryItemFields,
    ItineraryItemRecord,
    LongText,
    ShortText,
    StrictModel,
    TripIdentifier,
    TripRecord,
    _normalise_optional_text,
    _validate_iso_date,
)
from .prompt_assets import load_prompt_asset

LOGGER = logging.getLogger(__name__)
PROMPT_TEXT_LIMIT = 180
PROMPT_TRUNCATED_SUFFIX = "… [truncated]"
PROMPT_BUDGET_ERROR_FIELD = "ai_suggestions"
PROMPT_JSON_SORT_KEYS = True

AiGoalText = Annotated[str, StringConstraints(min_length=1, max_length=800)]
AiOptionalText = Annotated[str, StringConstraints(max_length=1000)]
CorrelationId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=CORRELATION_ID_PATTERN.pattern,
    ),
]


class AiSuggestionRequest(StrictModel):
    requested_date: IsoDate
    goal: AiGoalText
    interests: AiOptionalText | None = None
    constraints: AiOptionalText | None = None

    @field_validator("requested_date")
    @classmethod
    def validate_requested_date(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("interests", "constraints")
    @classmethod
    def normalise_optional_fields(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class AiSuggestionDraft(ItineraryItemFields):
    rationale: LongText | None = None
    persisted: bool = False
    approval_required: bool = True

    @field_validator("rationale")
    @classmethod
    def normalise_rationale(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class AiSuggestionsResponse(StrictModel):
    trip_id: TripIdentifier
    requested_date: IsoDate
    model: ShortText
    prompt_asset: ShortText
    run_id: ShortText
    correlation_id: CorrelationId
    attempt_count: int = Field(
        ge=AI_MAX_ATTEMPTS_MIN,
        le=AI_MAX_ATTEMPTS_MAX,
    )
    persisted: bool = False
    approval_required: bool = True
    suggestions: list[AiSuggestionDraft] = Field(default_factory=list, max_length=5)

    @field_validator("requested_date")
    @classmethod
    def validate_response_date(cls, value: str) -> str:
        return _validate_iso_date(value)


class AiModeSuggestionDraft(ItineraryItemFields):
    rationale: LongText | None = None

    @field_validator("rationale")
    @classmethod
    def normalise_rationale(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class AiModeSuggestionEnvelope(StrictModel):
    suggestions: list[AiModeSuggestionDraft] = Field(default_factory=list, max_length=5)


PromptText = Annotated[str, StringConstraints(max_length=PROMPT_TEXT_LIMIT)]


class PromptBudgetAdjustments(StrictModel):
    item_notes: int | None = Field(default=None, ge=1)
    item_descriptions: int | None = Field(default=None, ge=1)
    item_locations: int | None = Field(default=None, ge=1)
    trip_notes: bool | None = None
    interests: bool | None = None
    constraints: bool | None = None
    dropped_items: int | None = Field(default=None, ge=1)


class PromptContextItem(StrictModel):
    date: IsoDate
    start_time: str | None = None
    end_time: str | None = None
    title: ShortText
    category: ItineraryCategory
    location: ShortText | None = None
    description_excerpt: PromptText | None = None
    notes_excerpt: PromptText | None = None

    @field_validator("date")
    @classmethod
    def validate_prompt_date(cls, value: str) -> str:
        return _validate_iso_date(value)


class PromptContext(StrictModel):
    destination: ShortText
    start_date: IsoDate
    end_date: IsoDate
    traveller_count: int = Field(ge=1, le=1000)
    trip_notes_excerpt: PromptText | None = None
    requested_date: IsoDate
    goal: AiGoalText
    interests: AiOptionalText | None = None
    constraints: AiOptionalText | None = None
    total_existing_items: int = Field(ge=0)
    omitted_existing_items: int = Field(ge=0)
    existing_items: list[PromptContextItem] = Field(default_factory=list)
    budget_adjustments: PromptBudgetAdjustments | None = None

    @field_validator("start_date", "end_date", "requested_date")
    @classmethod
    def validate_context_dates(cls, value: str) -> str:
        return _validate_iso_date(value)


@dataclass(slots=True)
class RetryableAiFailure(Exception):
    kind: str
    summary: str
    details: list[dict[str, str]]


@dataclass(slots=True)
class PreparedPrompt:
    prompt: str
    prompt_context: PromptContext


@dataclass(slots=True)
class PromptBudgetState:
    item_notes: int = 0
    item_descriptions: int = 0
    item_locations: int = 0
    trip_notes: bool = False
    interests: bool = False
    constraints: bool = False
    dropped_items: int = 0


def build_prompt_context(
    trip: TripRecord,
    existing_items: list[ItineraryItemRecord],
    request: AiSuggestionRequest,
    settings: Settings,
) -> PromptContext:
    prioritised_items = sorted(
        existing_items,
        key=lambda item: (
            0 if item.date == request.requested_date else 1,
            abs(
                (
                    date.fromisoformat(item.date)
                    - date.fromisoformat(request.requested_date)
                ).days
            ),
            item.date,
            1 if item.start_time is None else 0,
            item.start_time or "",
            item.title.casefold(),
            item.id,
        ),
    )
    limited_items = prioritised_items[: settings.ai_max_context_items]

    return PromptContext(
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        traveller_count=trip.traveller_count,
        trip_notes_excerpt=_truncate_prompt_text(trip.notes),
        requested_date=request.requested_date,
        goal=request.goal,
        interests=request.interests,
        constraints=request.constraints,
        total_existing_items=len(existing_items),
        omitted_existing_items=max(
            len(existing_items) - len(limited_items),
            0,
        ),
        existing_items=[
            PromptContextItem(
                date=item.date,
                start_time=item.start_time,
                end_time=item.end_time,
                title=item.title,
                category=item.category,
                location=item.location,
                description_excerpt=_truncate_prompt_text(item.description),
                notes_excerpt=_truncate_prompt_text(item.notes),
            )
            for item in limited_items
        ],
    )


class AiSuggestionService:
    def __init__(self, client: AiModeClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def dependency_status(self) -> DependencyStatus:
        return await self._client.health()

    def readiness_dependency_status(self) -> DependencyStatus:
        return self._client.readiness_status()

    async def generate(
        self,
        *,
        trip_id: str,
        trip: TripRecord,
        existing_items: list[ItineraryItemRecord],
        request: AiSuggestionRequest,
        correlation_id: str | None = None,
    ) -> AiSuggestionsResponse:
        run_id = f"ai_{uuid4().hex[:12]}"
        resolved_correlation_id = _normalise_correlation_id(correlation_id, run_id)
        base_prompt_context = build_prompt_context(
            trip,
            existing_items,
            request,
            self._settings,
        )
        prompt_schema = AiModeSuggestionEnvelope.model_json_schema()
        prompt_asset = self._settings.ai_prompt_asset

        _log_stage(
            "start",
            run_id=run_id,
            correlation_id=resolved_correlation_id,
            trip_id=trip_id,
            requested_date=request.requested_date,
            prompt_asset=prompt_asset,
            goal_chars=len(request.goal),
            interests_chars=len(request.interests or ""),
            constraints_chars=len(request.constraints or ""),
            context_items=len(base_prompt_context.existing_items),
            omitted_items=base_prompt_context.omitted_existing_items,
        )

        failure_note: str | None = None
        last_failure: RetryableAiFailure | None = None

        for attempt in range(1, self._settings.ai_max_attempts + 1):
            prepared_prompt = build_budgeted_prompt(
                prompt_asset=prompt_asset,
                prompt_context=base_prompt_context,
                output_schema=prompt_schema,
                failure_note=failure_note,
                max_prompt_chars=self._settings.ai_mode_max_prompt_chars,
            )
            _log_stage(
                "ai_mode_attempt",
                run_id=run_id,
                correlation_id=resolved_correlation_id,
                trip_id=trip_id,
                attempt=attempt,
                prompt_chars=len(prepared_prompt.prompt),
                context_items=len(prepared_prompt.prompt_context.existing_items),
                omitted_items=prepared_prompt.prompt_context.omitted_existing_items,
                budgeted=prepared_prompt.prompt_context.budget_adjustments is not None,
            )
            generation = await self._client.generate(
                prompt=prepared_prompt.prompt,
                schema=prompt_schema,
                correlation_id=resolved_correlation_id,
                metadata={
                    "feature": "student-1-trip-suggestions",
                    "trip_id": trip_id,
                    "requested_date": request.requested_date,
                    "attempt": str(attempt),
                    "prompt_asset": prompt_asset,
                },
            )
            try:
                suggestions = normalise_suggestions(
                    trip=trip,
                    requested_date=request.requested_date,
                    existing_items=existing_items,
                    payload_text=generation.response,
                )
            except RetryableAiFailure as exc:
                last_failure = exc
                _log_stage(
                    "retryable_failure",
                    run_id=run_id,
                    correlation_id=resolved_correlation_id,
                    trip_id=trip_id,
                    attempt=attempt,
                    ai_mode_run_id=generation.run_id,
                    failure_kind=exc.kind,
                    summary=exc.summary,
                )
                if attempt >= self._settings.ai_max_attempts:
                    break
                failure_note = build_failure_note(exc, request.requested_date)
                continue

            _log_stage(
                "success",
                run_id=run_id,
                correlation_id=resolved_correlation_id,
                trip_id=trip_id,
                attempt=attempt,
                suggestion_count=len(suggestions),
            )
            return AiSuggestionsResponse(
                trip_id=trip_id,
                requested_date=request.requested_date,
                model=generation.model,
                prompt_asset=prompt_asset,
                run_id=generation.run_id,
                correlation_id=generation.correlation_id,
                attempt_count=attempt,
                persisted=False,
                approval_required=True,
                suggestions=suggestions,
            )

        exhausted_failure = last_failure or RetryableAiFailure(
            kind="unknown",
            summary="model output could not be recovered",
            details=[{"field": "ai_suggestions", "issue": "runtime validation failed"}],
        )
        _log_stage(
            "retry_exhausted",
            run_id=run_id,
            correlation_id=resolved_correlation_id,
            trip_id=trip_id,
            attempt=self._settings.ai_max_attempts,
            failure_kind=exhausted_failure.kind,
            summary=exhausted_failure.summary,
        )
        raise ai_output_invalid(
            (
                "AI-generated suggestions could not be validated after "
                f"{self._settings.ai_max_attempts} attempt(s)."
            ),
            [
                {
                    "field": "ai_suggestions",
                    "issue": "runtime validation retries were exhausted",
                },
                *exhausted_failure.details[:3],
            ],
        )


def normalise_suggestions(
    *,
    trip: TripRecord,
    requested_date: str,
    existing_items: list[ItineraryItemRecord],
    payload_text: str,
) -> list[AiSuggestionDraft]:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RetryableAiFailure(
            kind="parse",
            summary="response body was not valid JSON",
            details=[
                {
                    "field": "response",
                    "issue": "model did not return valid JSON",
                },
            ],
        ) from exc

    try:
        envelope = AiModeSuggestionEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise RetryableAiFailure(
            kind="schema",
            summary="response body did not match the required suggestion schema",
            details=_validation_details_from_error(exc, prefix="suggestions"),
        ) from exc

    draft_items: list[AiSuggestionDraft] = []
    validation_errors: list[dict[str, str]] = []

    same_day_existing_items = [
        item for item in existing_items if item.date == requested_date
    ]

    for index, suggestion in enumerate(envelope.suggestions):
        raw_item = suggestion.model_dump(mode="json")
        field_prefix = f"suggestions[{index}]"
        validation_item = {
            key: value
            for key, value in raw_item.items()
            if key != "rationale"
        }

        try:
            ItineraryItemCreate.model_validate(validation_item)
        except ValidationError as exc:
            validation_errors.extend(
                _validation_details_from_error(exc, prefix=field_prefix)
            )
            continue

        item_date = raw_item["date"]
        if item_date < trip.start_date or item_date > trip.end_date:
            validation_errors.append(
                {
                    "field": f"{field_prefix}.date",
                    "issue": (
                        f"must fall between {trip.start_date} and {trip.end_date}"
                    ),
                },
            )
        if item_date != requested_date:
            validation_errors.append(
                {
                    "field": f"{field_prefix}.date",
                    "issue": f"must match the requested date {requested_date}",
                },
            )

        start_time = raw_item.get("start_time")
        end_time = raw_item.get("end_time")
        if start_time is not None and end_time is not None and start_time >= end_time:
            validation_errors.append(
                {
                    "field": f"{field_prefix}.start_time",
                    "issue": "must be earlier than end_time when both are provided",
                },
            )

        draft_item = AiSuggestionDraft(
            **raw_item,
            persisted=False,
            approval_required=True,
        )

        duplicate_existing = _find_duplicate(draft_item, same_day_existing_items)
        if duplicate_existing is not None:
            validation_errors.append(
                {
                    "field": field_prefix,
                    "issue": (
                        "duplicates the existing itinerary item "
                        f"'{duplicate_existing.title}'"
                    ),
                },
            )

        conflict_existing = _find_time_conflict(draft_item, same_day_existing_items)
        if conflict_existing is not None:
            validation_errors.append(
                {
                    "field": field_prefix,
                    "issue": (
                        "conflicts with the existing itinerary item "
                        f"'{conflict_existing.title}'"
                    ),
                },
            )

        duplicate_draft = _find_duplicate(draft_item, draft_items)
        if duplicate_draft is not None:
            validation_errors.append(
                {
                    "field": field_prefix,
                    "issue": (
                        "duplicates another suggested itinerary item "
                        f"'{duplicate_draft.title}'"
                    ),
                },
            )

        conflict_draft = _find_time_conflict(draft_item, draft_items)
        if conflict_draft is not None:
            validation_errors.append(
                {
                    "field": field_prefix,
                    "issue": (
                        "conflicts with another suggested itinerary item "
                        f"'{conflict_draft.title}'"
                    ),
                },
            )

        draft_items.append(draft_item)

    if validation_errors:
        raise RetryableAiFailure(
            kind="constraint",
            summary="suggestions violated TripGenie itinerary rules",
            details=validation_errors,
        )

    return sorted(
        draft_items,
        key=lambda item: (
            item.date,
            1 if item.start_time is None else 0,
            item.start_time or "",
            item.title.casefold(),
        ),
    )


def build_failure_note(failure: RetryableAiFailure, requested_date: str) -> str:
    detail_lines = "\n".join(
        f"- {detail['field']}: {detail['issue']}" for detail in failure.details[:3]
    )
    return (
        "The previous response could not be used.\n"
        f"Reason: {failure.summary}.\n"
        f"Requested date: {requested_date}.\n"
        "Regenerate the full response from scratch, return JSON only, keep every "
        "suggestion on the requested date, avoid duplicates or overlapping timed "
        "items, and satisfy the exact schema.\n"
        f"{detail_lines}"
    )


def render_prompt(
    *,
    prompt_asset: str,
    prompt_context: PromptContext,
    output_schema: dict[str, object],
    failure_note: str | None,
) -> str:
    template = load_prompt_asset(prompt_asset)
    return _render_prompt_with_context_data(
        template=template,
        context_data=prompt_context.model_dump(mode="json", exclude_none=True),
        output_schema_json=_dump_compact_json(output_schema),
        failure_note=failure_note,
    )


def build_budgeted_prompt(
    *,
    prompt_asset: str,
    prompt_context: PromptContext,
    output_schema: dict[str, object],
    failure_note: str | None,
    max_prompt_chars: int,
) -> PreparedPrompt:
    template = load_prompt_asset(prompt_asset)
    output_schema_json = _dump_compact_json(output_schema)
    context_data = prompt_context.model_dump(mode="json", exclude_none=True)
    budget_state = PromptBudgetState()

    while True:
        _apply_budget_adjustments(context_data, budget_state)
        rendered_prompt = _render_prompt_with_context_data(
            template=template,
            context_data=context_data,
            output_schema_json=output_schema_json,
            failure_note=failure_note,
        )
        if len(rendered_prompt) <= max_prompt_chars:
            return PreparedPrompt(
                prompt=rendered_prompt,
                prompt_context=PromptContext.model_validate(context_data),
            )

        if _omit_item_field(context_data, field_name="notes_excerpt"):
            budget_state.item_notes += 1
            continue
        if _omit_item_field(context_data, field_name="description_excerpt"):
            budget_state.item_descriptions += 1
            continue
        if _omit_top_level_field(context_data, field_name="trip_notes_excerpt"):
            budget_state.trip_notes = True
            continue
        if _omit_top_level_field(context_data, field_name="interests"):
            budget_state.interests = True
            continue
        if _omit_top_level_field(context_data, field_name="constraints"):
            budget_state.constraints = True
            continue
        if _omit_item_field(context_data, field_name="location"):
            budget_state.item_locations += 1
            continue
        if _drop_low_priority_item(context_data):
            budget_state.dropped_items += 1
            continue

        raise validation_error(
            "One or more fields failed validation.",
            [
                {
                    "field": PROMPT_BUDGET_ERROR_FIELD,
                    "issue": (
                        "required trip context exceeds the configured AI prompt "
                        f"budget of {max_prompt_chars} characters"
                    ),
                },
            ],
        )


def _render_prompt_with_context_data(
    *,
    template: str,
    context_data: dict[str, object],
    output_schema_json: str,
    failure_note: str | None,
) -> str:
    rendered = template.replace(
        "{{TRIP_CONTEXT_JSON}}",
        _dump_compact_json(context_data),
    ).replace(
        "{{OUTPUT_SCHEMA_JSON}}",
        output_schema_json,
    )
    adaptation_block = failure_note or "None."
    return rendered.replace("{{ADAPTATION_NOTES}}", adaptation_block).strip()


def _dump_compact_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=PROMPT_JSON_SORT_KEYS,
    )


def _apply_budget_adjustments(
    context_data: dict[str, object],
    budget_state: PromptBudgetState,
) -> None:
    adjustments: dict[str, object] = {}
    if budget_state.item_notes:
        adjustments["item_notes"] = budget_state.item_notes
    if budget_state.item_descriptions:
        adjustments["item_descriptions"] = budget_state.item_descriptions
    if budget_state.item_locations:
        adjustments["item_locations"] = budget_state.item_locations
    if budget_state.trip_notes:
        adjustments["trip_notes"] = True
    if budget_state.interests:
        adjustments["interests"] = True
    if budget_state.constraints:
        adjustments["constraints"] = True
    if budget_state.dropped_items:
        adjustments["dropped_items"] = budget_state.dropped_items

    if adjustments:
        context_data["budget_adjustments"] = adjustments
        return

    context_data.pop("budget_adjustments", None)


def _omit_top_level_field(
    context_data: dict[str, object],
    *,
    field_name: str,
) -> bool:
    if field_name not in context_data:
        return False
    del context_data[field_name]
    return True


def _omit_item_field(
    context_data: dict[str, object],
    *,
    field_name: str,
) -> bool:
    items = _context_items(context_data)
    for item in reversed(items):
        if field_name in item:
            del item[field_name]
            return True
    return False


def _drop_low_priority_item(context_data: dict[str, object]) -> bool:
    items = _context_items(context_data)
    if not items:
        return False
    items.pop()
    if items:
        context_data["existing_items"] = items
    else:
        context_data.pop("existing_items", None)
    context_data["omitted_existing_items"] = int(
        context_data.get("omitted_existing_items", 0)
    ) + 1
    return True


def _context_items(context_data: dict[str, object]) -> list[dict[str, object]]:
    existing_items = context_data.get("existing_items")
    if not isinstance(existing_items, list):
        return []
    return existing_items


def _validation_details_from_error(
    exc: ValidationError,
    *,
    prefix: str,
) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        field_name = f"{prefix}.{location}" if location else prefix
        details.append({"field": field_name, "issue": error["msg"]})
    return details or [{"field": prefix, "issue": "response did not match schema"}]


def _find_duplicate(
    candidate: AiSuggestionDraft,
    existing_items: list[ItineraryItemRecord | AiSuggestionDraft],
) -> ItineraryItemRecord | AiSuggestionDraft | None:
    candidate_signature = _duplicate_signature(candidate)
    for item in existing_items:
        if _duplicate_signature(item) == candidate_signature:
            return item
    return None


def _duplicate_signature(
    item: ItineraryItemRecord | AiSuggestionDraft,
) -> tuple[str, str, str, str, str]:
    return (
        item.date,
        item.category.value,
        item.title.casefold(),
        item.start_time or "",
        item.end_time or "",
    )


def _find_time_conflict(
    candidate: AiSuggestionDraft,
    existing_items: list[ItineraryItemRecord | AiSuggestionDraft],
) -> ItineraryItemRecord | AiSuggestionDraft | None:
    candidate_range = _time_range(candidate.start_time, candidate.end_time)
    if candidate_range is None:
        return None

    for item in existing_items:
        if item.date != candidate.date:
            continue
        existing_range = _time_range(item.start_time, item.end_time)
        if existing_range is None:
            continue
        if max(candidate_range[0], existing_range[0]) < min(
            candidate_range[1],
            existing_range[1],
        ):
            return item
    return None


def _time_range(
    start_time: str | None,
    end_time: str | None,
) -> tuple[time, time] | None:
    if start_time is None or end_time is None:
        return None
    return (time.fromisoformat(start_time), time.fromisoformat(end_time))


def _truncate_prompt_text(value: str | None) -> str | None:
    cleaned = _normalise_optional_text(value)
    if cleaned is None:
        return None
    if len(cleaned) <= PROMPT_TEXT_LIMIT:
        return cleaned
    truncated_limit = PROMPT_TEXT_LIMIT - len(PROMPT_TRUNCATED_SUFFIX)
    return f"{cleaned[:truncated_limit].rstrip()}{PROMPT_TRUNCATED_SUFFIX}"


def _normalise_correlation_id(correlation_id: str | None, fallback: str) -> str:
    if correlation_id is None or not correlation_id.strip():
        return fallback

    try:
        return validate_correlation_id_value(correlation_id)
    except ValueError as exc:
        raise validation_error(
            "One or more fields failed validation.",
            [{"field": "correlation_id", "issue": str(exc)}],
        ) from exc


def _log_stage(stage: str, **payload: object) -> None:
    serialised = " ".join(
        f"{key}={sanitise_log_value(payload[key])}" for key in sorted(payload)
    )
    LOGGER.info("student1.ai_suggestions stage=%s %s", stage, serialised)
