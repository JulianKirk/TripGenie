from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

TripIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=6,
        max_length=64,
        pattern=r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$",
    ),
]
ItemIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=6,
        max_length=64,
        pattern=r"^item_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$",
    ),
]
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
IsoTime = Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(max_length=2000)]

T = TypeVar("T")


def _validate_iso_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be a valid ISO date in YYYY-MM-DD format") from exc

    return value


def _validate_iso_time(value: str) -> str:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be a valid HH:MM time") from exc

    if parsed.second or parsed.microsecond:
        raise ValueError("must be a valid HH:MM time")

    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TripStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ItineraryCategory(str, Enum):
    ACCOMMODATION = "accommodation"
    TRANSPORT = "transport"
    ACTIVITY = "activity"
    MEAL = "meal"
    NOTE = "note"
    OTHER = "other"


class ErrorDetail(StrictModel):
    field: str
    issue: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(StrictModel):
    error: ErrorBody


class DataEnvelope(StrictModel, Generic[T]):
    data: T


class TripFields(StrictModel):
    name: ShortText
    destination: ShortText
    start_date: IsoDate
    end_date: IsoDate
    traveller_count: int = Field(ge=1, le=1000)
    status: TripStatus
    notes: LongText | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_fields(cls, value: str) -> str:
        return _validate_iso_date(value)


class TripRecord(TripFields):
    id: TripIdentifier


class ItineraryItemFields(StrictModel):
    date: IsoDate
    start_time: IsoTime | None = None
    end_time: IsoTime | None = None
    title: ShortText
    location: ShortText | None = None
    description: LongText | None = None
    category: ItineraryCategory
    notes: LongText | None = None

    @field_validator("date")
    @classmethod
    def validate_item_date(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_item_time(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return _validate_iso_time(value)


class ItineraryItemRecord(ItineraryItemFields):
    id: ItemIdentifier
    trip_id: TripIdentifier


class TripDay(StrictModel):
    date: IsoDate
    items: list[ItineraryItemRecord] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def validate_trip_day_date(cls, value: str) -> str:
        return _validate_iso_date(value)


class TripDetail(TripRecord):
    days: list[TripDay] = Field(default_factory=list)


class DeleteResponse(StrictModel):
    id: str
    deleted: bool = True


class AiSuggestionDraft(ItineraryItemFields):
    rationale: LongText | None = None
    persisted: bool = False
    approval_required: bool = True


class AiSuggestionsResponse(StrictModel):
    trip_id: TripIdentifier
    requested_date: IsoDate
    model: ShortText
    prompt_asset: ShortText
    run_id: ShortText
    correlation_id: ShortText
    attempt_count: int = Field(ge=1, le=10)
    persisted: bool = False
    approval_required: bool = True
    suggestions: list[AiSuggestionDraft] = Field(default_factory=list, max_length=5)


class BackendDependencyPayload(StrictModel):
    status: ShortText
    service: ShortText
    detail: LongText | None = None
    code: ShortText | None = None


class BackendHealthDependencies(StrictModel):
    database: BackendDependencyPayload
    ai_mode: BackendDependencyPayload


class BackendHealthPayload(StrictModel):
    status: ShortText
    service: ShortText
    dependencies: BackendHealthDependencies


class DependencyStatus(StrictModel):
    status: ShortText
    service: ShortText
    detail: LongText | None = None
    code: ShortText | None = None


class FrontendHealthDependencies(StrictModel):
    backend: DependencyStatus


class HealthResponse(StrictModel):
    status: ShortText
    service: ShortText
    dependencies: FrontendHealthDependencies
