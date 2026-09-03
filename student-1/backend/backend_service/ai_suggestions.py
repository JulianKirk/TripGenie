from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

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
    ItineraryItemCreate,
    ItineraryItemFields,
    ItineraryItemRecord,
    LongText,
    ShortText,
    StrictModel,
    TripAccommodationDetail,
    TripAccommodationRecord,
    TripActivityDetail,
    TripActivityRecord,
    TripIdentifier,
    TripRecord,
    TripTransportDetail,
    TripTransportRecord,
    _normalise_optional_text,
    _validate_iso_date,
)
from .prompt_assets import load_prompt_asset

LOGGER = logging.getLogger(__name__)
PROMPT_TEXT_LIMIT = 180
PROMPT_TRUNCATED_SUFFIX = "… [truncated]"
PROMPT_BUDGET_ERROR_FIELD = "ai_suggestions"
PROMPT_JSON_SORT_KEYS = True
AI_SUGGESTION_MAX_COUNT = 3
PROMPT_PLACEHOLDER_PATTERN = re.compile(
    r"\{\{(TRIP_CONTEXT_JSON|OUTPUT_SCHEMA_JSON|ADAPTATION_NOTES|MAX_SUGGESTIONS)\}\}"
)

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
    suggestions: list[AiSuggestionDraft] = Field(
        default_factory=list,
        max_length=AI_SUGGESTION_MAX_COUNT,
    )

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
    suggestions: list[AiModeSuggestionDraft] = Field(
        default_factory=list,
        max_length=AI_SUGGESTION_MAX_COUNT,
    )


PromptText = Annotated[str, StringConstraints(max_length=PROMPT_TEXT_LIMIT)]


class _PromptModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _PromptBudgetAdjustments(_PromptModel):
    item_notes: int | None = Field(default=None, ge=1)
    item_descriptions: int | None = Field(default=None, ge=1)
    item_locations: int | None = Field(default=None, ge=1)
    trip_notes: bool | None = None
    interests: bool | None = None
    dropped_accommodations: int | None = Field(default=None, ge=1)
    dropped_activities: int | None = Field(default=None, ge=1)
    dropped_transport: int | None = Field(default=None, ge=1)
    dropped_items: int | None = Field(default=None, ge=1)


class _PromptContextItem(_PromptModel):
    date: IsoDate
    start_time: str | None = None
    end_time: str | None = None
    title: ShortText
    category: str
    location: ShortText | None = None
    description_excerpt: PromptText | None = None
    notes_excerpt: PromptText | None = None

    @field_validator("date")
    @classmethod
    def validate_prompt_date(cls, value: str) -> str:
        return _validate_iso_date(value)


_SourceStatus = Literal["available", "partial", "unavailable"]


class _PromptAccommodationContext(_PromptModel):
    accommodation_id: str
    source_status: _SourceStatus
    name: PromptText | None = None
    location: PromptText | None = None
    check_in: IsoDate
    check_in_time: str | None = None
    check_out: IsoDate | None = None
    check_out_time: str | None = None

    @field_validator("check_in", "check_out")
    @classmethod
    def validate_dates(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_date(value)


class _PromptActivityContext(_PromptModel):
    activity_id: str
    source_status: _SourceStatus
    name: PromptText | None = None
    date: IsoDate
    start_time: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    price: str | None = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso_date(value)


class _PromptTransportContext(_PromptModel):
    transport_id: str
    source_status: _SourceStatus
    mode: PromptText | None = None
    provider: PromptText | None = None
    departure: PromptText | None = None
    arrival: PromptText | None = None
    origin: PromptText | None = None
    destination: PromptText | None = None
    price: float | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, gt=0)
    traveller_count: int = Field(ge=1, le=1000)
    plan_status: str


class _CrossServicePromptContext(_PromptModel):
    total_selected_accommodations: int = Field(ge=0)
    omitted_selected_accommodations: int = Field(ge=0)
    selected_accommodations: list[_PromptAccommodationContext] = Field(
        default_factory=list
    )
    total_selected_activities: int = Field(ge=0)
    omitted_selected_activities: int = Field(ge=0)
    selected_activities: list[_PromptActivityContext] = Field(default_factory=list)
    total_selected_transport: int = Field(ge=0)
    omitted_selected_transport: int = Field(ge=0)
    selected_transport: list[_PromptTransportContext] = Field(default_factory=list)


class _PromptContext(_PromptModel):
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
    existing_items: list[_PromptContextItem] = Field(default_factory=list)
    total_selected_accommodations: int = Field(ge=0)
    omitted_selected_accommodations: int = Field(ge=0)
    selected_accommodations: list[_PromptAccommodationContext] = Field(
        default_factory=list
    )
    total_selected_activities: int = Field(ge=0)
    omitted_selected_activities: int = Field(ge=0)
    selected_activities: list[_PromptActivityContext] = Field(default_factory=list)
    total_selected_transport: int = Field(ge=0)
    omitted_selected_transport: int = Field(ge=0)
    selected_transport: list[_PromptTransportContext] = Field(default_factory=list)
    budget_adjustments: _PromptBudgetAdjustments | None = None

    @field_validator("start_date", "end_date", "requested_date")
    @classmethod
    def validate_context_dates(cls, value: str) -> str:
        return _validate_iso_date(value)


class _PromptRetryDetail(_PromptModel):
    field: PromptText
    issue: PromptText


class _PromptRetryContext(_PromptModel):
    status: Literal["none", "retry"]
    failure_kind: Literal["parse", "schema", "constraint"] | None = None
    summary: PromptText | None = None
    requested_date: IsoDate | None = None
    details: list[_PromptRetryDetail] = Field(default_factory=list, max_length=3)

    @field_validator("requested_date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_date(value)


@dataclass(slots=True)
class RetryableAiFailure(Exception):
    kind: str
    summary: str
    details: list[dict[str, str]]


@dataclass(slots=True)
class _PreparedPrompt:
    prompt: str
    prompt_context: _PromptContext


@dataclass(slots=True)
class _PromptBudgetState:
    item_notes: int = 0
    item_descriptions: int = 0
    item_locations: int = 0
    trip_notes: bool = False
    interests: bool = False
    dropped_accommodations: int = 0
    dropped_activities: int = 0
    dropped_transport: int = 0
    dropped_items: int = 0


@dataclass(frozen=True, slots=True)
class _SelectedCrossServiceRecords:
    total_accommodations: int
    omitted_accommodations: int
    accommodations: list[TripAccommodationRecord]
    total_activities: int
    omitted_activities: int
    activities: list[TripActivityRecord]
    total_transport: int
    omitted_transport: int
    transport: list[TripTransportRecord]


@dataclass(frozen=True, slots=True)
class _AuthoritativeTimeBlock:
    source_type: Literal["activity", "transport"]
    source_id: str
    start: datetime
    end: datetime


def select_cross_service_records(
    *,
    accommodations: list[TripAccommodationRecord],
    activities: list[TripActivityRecord],
    transport: list[TripTransportRecord],
    request: AiSuggestionRequest,
    settings: Settings,
) -> _SelectedCrossServiceRecords:
    prioritised_accommodations = sorted(
        accommodations,
        key=lambda item: (
            0
            if (
                item.date <= request.requested_date
                and (item.check_out is None or request.requested_date <= item.check_out)
            )
            else 1,
            item.date,
            item.check_in_time or "",
            item.accommodation_id,
        ),
    )
    prioritised_activities = sorted(
        activities,
        key=lambda item: (
            0 if item.date == request.requested_date else 1,
            abs(
                (
                    date.fromisoformat(item.date)
                    - date.fromisoformat(request.requested_date)
                ).days
            ),
            item.date,
            item.start_time or "",
            item.activity_id,
        ),
    )
    transport_status_priority = {
        "confirmed": 0,
        "pending": 1,
        "completed": 2,
        "cancelled": 3,
    }
    prioritised_transport = sorted(
        transport,
        key=lambda item: (
            transport_status_priority[item.plan_status.value],
            item.added_on,
            item.transport_id,
        ),
    )
    selected_accommodations = prioritised_accommodations[
        : settings.ai_max_context_accommodations
    ]
    selected_activities = prioritised_activities[: settings.ai_max_context_activities]
    selected_transport = prioritised_transport[: settings.ai_max_context_transport]
    return _SelectedCrossServiceRecords(
        total_accommodations=len(accommodations),
        omitted_accommodations=max(
            len(accommodations) - len(selected_accommodations),
            0,
        ),
        accommodations=selected_accommodations,
        total_activities=len(activities),
        omitted_activities=max(len(activities) - len(selected_activities), 0),
        activities=selected_activities,
        total_transport=len(transport),
        omitted_transport=max(len(transport) - len(selected_transport), 0),
        transport=selected_transport,
    )


def prepare_cross_service_prompt_context(
    *,
    selection: _SelectedCrossServiceRecords,
    enriched_accommodations: list[TripAccommodationDetail],
    accommodation_sources: dict[str, dict[str, Any]],
    enriched_activities: list[TripActivityDetail],
    enriched_transport: list[TripTransportDetail],
) -> _CrossServicePromptContext:
    accommodations_by_id = {
        item.accommodation_id: item for item in enriched_accommodations
    }
    activities_by_id = {item.activity_id: item for item in enriched_activities}
    transport_by_id = {item.transport_id: item for item in enriched_transport}

    accommodation_context: list[_PromptAccommodationContext] = []
    for pin in selection.accommodations:
        enriched = accommodations_by_id[pin.accommodation_id]
        source = accommodation_sources.get(pin.accommodation_id)
        location = source.get("location") if source is not None else None
        accommodation_context.append(
            _PromptAccommodationContext(
                accommodation_id=pin.accommodation_id,
                source_status=_source_status(
                    source is not None,
                    (enriched.name, location),
                ),
                name=_truncate_prompt_text(enriched.name),
                location=_truncate_prompt_text(
                    location if isinstance(location, str) else None
                ),
                check_in=pin.date,
                check_in_time=pin.check_in_time,
                check_out=pin.check_out,
                check_out_time=pin.check_out_time,
            )
        )

    activity_context: list[_PromptActivityContext] = []
    for pin in selection.activities:
        enriched = activities_by_id[pin.activity_id]
        activity_context.append(
            _PromptActivityContext(
                activity_id=pin.activity_id,
                source_status=_source_status(
                    enriched.name is not None,
                    (enriched.name, enriched.price, enriched.duration_minutes),
                ),
                name=_truncate_prompt_text(enriched.name),
                date=pin.date,
                start_time=pin.start_time,
                duration_minutes=enriched.duration_minutes,
                price=enriched.price,
            )
        )

    transport_context: list[_PromptTransportContext] = []
    for pin in selection.transport:
        enriched = transport_by_id[pin.transport_id]
        transport_context.append(
            _PromptTransportContext(
                transport_id=pin.transport_id,
                source_status=_source_status(
                    enriched.type is not None,
                    (
                        enriched.type,
                        enriched.provider,
                        enriched.origin,
                        enriched.destination,
                        enriched.departure_time,
                        enriched.arrival_time,
                        enriched.price,
                        enriched.duration_minutes,
                    ),
                ),
                mode=_truncate_prompt_text(enriched.type),
                provider=_truncate_prompt_text(enriched.provider),
                departure=_truncate_prompt_text(enriched.departure_time),
                arrival=_truncate_prompt_text(enriched.arrival_time),
                origin=_truncate_prompt_text(enriched.origin),
                destination=_truncate_prompt_text(enriched.destination),
                price=enriched.price,
                duration_minutes=enriched.duration_minutes,
                traveller_count=pin.traveller_count,
                plan_status=pin.plan_status.value,
            )
        )

    return _CrossServicePromptContext(
        total_selected_accommodations=selection.total_accommodations,
        omitted_selected_accommodations=selection.omitted_accommodations,
        selected_accommodations=accommodation_context,
        total_selected_activities=selection.total_activities,
        omitted_selected_activities=selection.omitted_activities,
        selected_activities=activity_context,
        total_selected_transport=selection.total_transport,
        omitted_selected_transport=selection.omitted_transport,
        selected_transport=transport_context,
    )


def build_cross_service_time_blocks(
    *,
    selection: _SelectedCrossServiceRecords,
    enriched_activities: list[TripActivityDetail],
    enriched_transport: list[TripTransportDetail],
) -> list[_AuthoritativeTimeBlock]:
    blocks: list[_AuthoritativeTimeBlock] = []
    activities_by_id = {item.activity_id: item for item in enriched_activities}
    for pin in selection.activities:
        enriched = activities_by_id[pin.activity_id]
        if pin.start_time is None or enriched.duration_minutes is None:
            continue
        try:
            start = datetime.fromisoformat(f"{pin.date}T{pin.start_time}")
        except ValueError:
            continue
        end = start + timedelta(minutes=enriched.duration_minutes)
        if end <= start:
            continue
        blocks.append(
            _AuthoritativeTimeBlock(
                source_type="activity",
                source_id=pin.activity_id,
                start=start,
                end=end,
            )
        )

    transport_by_id = {item.transport_id: item for item in enriched_transport}
    for pin in selection.transport:
        enriched = transport_by_id[pin.transport_id]
        if (
            pin.plan_status.value == "cancelled"
            or enriched.departure_time is None
            or enriched.arrival_time is None
        ):
            continue
        try:
            start = datetime.fromisoformat(enriched.departure_time)
            end = datetime.fromisoformat(enriched.arrival_time)
        except ValueError:
            continue
        if end <= start:
            continue
        blocks.append(
            _AuthoritativeTimeBlock(
                source_type="transport",
                source_id=pin.transport_id,
                start=start,
                end=end,
            )
        )

    return sorted(
        blocks,
        key=lambda block: (
            block.start,
            block.end,
            block.source_type,
            block.source_id,
        ),
    )


def build_prompt_context(
    trip: TripRecord,
    existing_items: list[ItineraryItemRecord],
    request: AiSuggestionRequest,
    settings: Settings,
    cross_service_context: _CrossServicePromptContext | None = None,
) -> _PromptContext:
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
    cross_service = cross_service_context or _CrossServicePromptContext(
        total_selected_accommodations=0,
        omitted_selected_accommodations=0,
        total_selected_activities=0,
        omitted_selected_activities=0,
        total_selected_transport=0,
        omitted_selected_transport=0,
    )

    return _PromptContext(
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
            _PromptContextItem(
                date=item.date,
                start_time=item.start_time,
                end_time=item.end_time,
                title=item.title,
                category=item.category.value,
                location=item.location,
                description_excerpt=_truncate_prompt_text(item.description),
                notes_excerpt=_truncate_prompt_text(item.notes),
            )
            for item in limited_items
        ],
        **cross_service.model_dump(mode="python"),
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
        cross_service_context: _CrossServicePromptContext | None = None,
        authoritative_time_blocks: list[_AuthoritativeTimeBlock] | None = None,
        correlation_id: str | None = None,
    ) -> AiSuggestionsResponse:
        run_id = f"ai_{uuid4().hex[:12]}"
        resolved_correlation_id = _normalise_correlation_id(correlation_id, run_id)
        base_prompt_context = build_prompt_context(
            trip,
            existing_items,
            request,
            self._settings,
            cross_service_context,
        )
        resolved_time_blocks = authoritative_time_blocks or []
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
            accommodations=len(base_prompt_context.selected_accommodations),
            activities=len(base_prompt_context.selected_activities),
            transport=len(base_prompt_context.selected_transport),
        )

        retry_context = _PromptRetryContext(status="none")
        last_failure: RetryableAiFailure | None = None

        for attempt in range(1, self._settings.ai_max_attempts + 1):
            prepared_prompt = build_budgeted_prompt(
                prompt_asset=prompt_asset,
                prompt_context=base_prompt_context,
                output_schema=prompt_schema,
                retry_context=retry_context,
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
                accommodations=len(
                    prepared_prompt.prompt_context.selected_accommodations
                ),
                activities=len(prepared_prompt.prompt_context.selected_activities),
                transport=len(prepared_prompt.prompt_context.selected_transport),
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
                    authoritative_time_blocks=resolved_time_blocks,
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
                retry_context = build_failure_note(exc, request.requested_date)
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
    authoritative_time_blocks: list[_AuthoritativeTimeBlock],
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
            key: value for key, value in raw_item.items() if key != "rationale"
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

        authoritative_conflict = _find_authoritative_time_conflict(
            draft_item,
            authoritative_time_blocks,
        )
        if authoritative_conflict is not None:
            validation_errors.append(
                {
                    "field": field_prefix,
                    "issue": (
                        "conflicts with selected "
                        f"{authoritative_conflict.source_type} "
                        f"'{authoritative_conflict.source_id}'"
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


def build_failure_note(
    failure: RetryableAiFailure,
    requested_date: str,
) -> _PromptRetryContext:
    return _PromptRetryContext(
        status="retry",
        failure_kind=failure.kind,
        summary=_required_prompt_text(failure.summary),
        requested_date=requested_date,
        details=[
            _PromptRetryDetail(
                field=_required_prompt_text(detail["field"]),
                issue=_required_prompt_text(detail["issue"]),
            )
            for detail in failure.details[:3]
        ],
    )


def render_prompt(
    *,
    prompt_asset: str,
    prompt_context: _PromptContext,
    output_schema: dict[str, object],
    retry_context: _PromptRetryContext | None = None,
) -> str:
    template = load_prompt_asset(prompt_asset)
    return _render_prompt_with_context_data(
        template=template,
        context_data=prompt_context.model_dump(mode="json", exclude_none=True),
        output_schema_json=_dump_compact_json(output_schema),
        retry_context=retry_context or _PromptRetryContext(status="none"),
    )


def build_budgeted_prompt(
    *,
    prompt_asset: str,
    prompt_context: _PromptContext,
    output_schema: dict[str, object],
    retry_context: _PromptRetryContext | None = None,
    max_prompt_chars: int,
) -> _PreparedPrompt:
    template = load_prompt_asset(prompt_asset)
    output_schema_json = _dump_compact_json(output_schema)
    context_data = prompt_context.model_dump(mode="json", exclude_none=True)
    budget_state = _PromptBudgetState()

    while True:
        _apply_budget_adjustments(context_data, budget_state)
        rendered_prompt = _render_prompt_with_context_data(
            template=template,
            context_data=context_data,
            output_schema_json=output_schema_json,
            retry_context=retry_context or _PromptRetryContext(status="none"),
        )
        if len(rendered_prompt) <= max_prompt_chars:
            return _PreparedPrompt(
                prompt=rendered_prompt,
                prompt_context=_PromptContext.model_validate(context_data),
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
        if _drop_low_priority_cross_service_record(
            context_data,
            list_field="selected_transport",
            omitted_field="omitted_selected_transport",
        ):
            budget_state.dropped_transport += 1
            continue
        if _drop_low_priority_cross_service_record(
            context_data,
            list_field="selected_accommodations",
            omitted_field="omitted_selected_accommodations",
        ):
            budget_state.dropped_accommodations += 1
            continue
        if _drop_low_priority_cross_service_record(
            context_data,
            list_field="selected_activities",
            omitted_field="omitted_selected_activities",
        ):
            budget_state.dropped_activities += 1
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
    retry_context: _PromptRetryContext,
) -> str:
    replacements = {
        "TRIP_CONTEXT_JSON": _dump_compact_json(context_data),
        "OUTPUT_SCHEMA_JSON": output_schema_json,
        "ADAPTATION_NOTES": _dump_compact_json(
            retry_context.model_dump(mode="json", exclude_none=True)
        ),
        "MAX_SUGGESTIONS": str(AI_SUGGESTION_MAX_COUNT),
    }
    return PROMPT_PLACEHOLDER_PATTERN.sub(
        lambda match: replacements[match.group(1)],
        template,
    ).strip()


def _dump_compact_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=PROMPT_JSON_SORT_KEYS,
    )


def _apply_budget_adjustments(
    context_data: dict[str, object],
    budget_state: _PromptBudgetState,
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
    if budget_state.dropped_accommodations:
        adjustments["dropped_accommodations"] = budget_state.dropped_accommodations
    if budget_state.dropped_activities:
        adjustments["dropped_activities"] = budget_state.dropped_activities
    if budget_state.dropped_transport:
        adjustments["dropped_transport"] = budget_state.dropped_transport
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
    context_data["omitted_existing_items"] = (
        int(context_data.get("omitted_existing_items", 0)) + 1
    )
    return True


def _drop_low_priority_cross_service_record(
    context_data: dict[str, object],
    *,
    list_field: str,
    omitted_field: str,
) -> bool:
    records = context_data.get(list_field)
    if not isinstance(records, list) or not records:
        return False

    records.pop()
    if records:
        context_data[list_field] = records
    else:
        context_data.pop(list_field, None)
    context_data[omitted_field] = int(context_data.get(omitted_field, 0)) + 1
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


def _find_authoritative_time_conflict(
    candidate: AiSuggestionDraft,
    authoritative_time_blocks: list[_AuthoritativeTimeBlock],
) -> _AuthoritativeTimeBlock | None:
    candidate_range = _time_range(candidate.start_time, candidate.end_time)
    if candidate_range is None:
        return None
    candidate_start = datetime.combine(
        date.fromisoformat(candidate.date),
        candidate_range[0],
    )
    candidate_end = datetime.combine(
        date.fromisoformat(candidate.date),
        candidate_range[1],
    )
    for block in authoritative_time_blocks:
        if candidate_start < block.end and block.start < candidate_end:
            return block
    return None


def _time_range(
    start_time: str | None,
    end_time: str | None,
) -> tuple[time, time] | None:
    if start_time is None or end_time is None:
        return None
    return (time.fromisoformat(start_time), time.fromisoformat(end_time))


def _source_status(
    source_found: bool, values: tuple[object | None, ...]
) -> _SourceStatus:
    if not source_found:
        return "unavailable"
    if all(value is not None for value in values):
        return "available"
    return "partial"


def _required_prompt_text(value: str) -> str:
    return _truncate_prompt_text(value) or "unavailable"


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
