from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

MONEY_PATTERN = re.compile(r"^(?:0|[1-9]\d*)\.\d{2}$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _money(value: object) -> Decimal:
    if not isinstance(value, str) or MONEY_PATTERN.fullmatch(value) is None:
        message = "price must be a canonical decimal string with two places"
        raise ValueError(message)
    return Decimal(value)


def _local_time(value: object) -> dt.time:
    if not isinstance(value, str) or TIME_PATTERN.fullmatch(value) is None:
        message = "time must use local HH:MM format"
        raise ValueError(message)
    return dt.time.fromisoformat(value)


Money = Annotated[
    Decimal,
    BeforeValidator(_money),
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str),
]
LocalTime = Annotated[dt.time, BeforeValidator(_local_time)]
PricingBasis = Literal["PER_PERSON", "FLAT_ADMISSION"]
DayOfWeek = Literal[
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"
]
CategoryCode = Literal[
    "ADVENTURE",
    "CULTURE",
    "FAMILY",
    "FOOD_DRINK",
    "NIGHTLIFE",
    "OUTDOOR",
    "SHOPPING",
    "TOUR",
    "WELLNESS",
    "WILDLIFE",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Category(StrictModel):
    code: CategoryCode
    label: str
    description: str | None = None
    display_order: int = Field(ge=0, strict=True)


class CategoryList(StrictModel):
    categories: list[Category]


class PublicLocation(StrictModel):
    country: str | None = None
    city: str | None = None
    street: str | None = None
    street_number: int | None = Field(default=None, ge=0, strict=True)


class PublicLocationWrite(StrictModel):
    country: str
    city: str
    street: str | None = None
    street_number: int | None = Field(default=None, ge=0, strict=True)


class ScheduleWrite(StrictModel):
    recurring_weekly: bool = Field(strict=True)
    day_of_week: DayOfWeek | None = None
    date: dt.date | None = None
    start_time: LocalTime
    end_time: LocalTime

    @field_serializer("start_time", "end_time")
    def serialize_time(self, value: dt.time) -> str:
        return value.strftime("%H:%M")

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.recurring_weekly != (self.day_of_week is not None):
            message = "weekly schedules require day_of_week"
            raise ValueError(message)
        if self.recurring_weekly == (self.date is not None):
            message = "one-off schedules require date"
            raise ValueError(message)
        if self.start_time >= self.end_time:
            message = "start_time must precede end_time"
            raise ValueError(message)
        return self

    def identity(self) -> tuple[bool, str | None, dt.date | None, dt.time, dt.time]:
        return (
            self.recurring_weekly,
            self.day_of_week,
            self.date,
            self.start_time,
            self.end_time,
        )

    def interval_minutes(self) -> int:
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return end - start


class Schedule(ScheduleWrite):
    id: UUID


class ActivityCommon(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    price: Money
    pricing_basis: PricingBasis
    duration_minutes: int = Field(gt=0, strict=True)
    minimum_age: int | None = Field(default=None, ge=0, strict=True)
    maximum_age: int | None = Field(default=None, ge=0, strict=True)
    minimum_participants: int = Field(ge=1, strict=True)
    maximum_participants: int | None = Field(default=None, ge=1, strict=True)
    booking_required: bool = Field(strict=True)
    wheelchair_accessible: bool | None = Field(default=None, strict=True)
    step_free_access: bool | None = Field(default=None, strict=True)
    accessible_toilet: bool | None = Field(default=None, strict=True)
    is_active: bool = Field(strict=True)
    categories: list[CategoryCode] = Field(min_length=1)

    @field_validator("name", "description")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            message = "must not be blank"
            raise ValueError(message)
        return value.strip()

    @field_validator("maximum_age")
    @classmethod
    def ordered_ages(cls, value: int | None, info: ValidationInfo) -> int | None:
        minimum = info.data.get("minimum_age")
        if minimum is not None and value is not None and minimum > value:
            message = "maximum_age must be at least minimum_age"
            raise ValueError(message)
        return value

    @field_validator("maximum_participants")
    @classmethod
    def ordered_participants(
        cls, value: int | None, info: ValidationInfo
    ) -> int | None:
        minimum = info.data.get("minimum_participants")
        if minimum is not None and value is not None and minimum > value:
            message = "maximum_participants must be at least minimum_participants"
            raise ValueError(message)
        return value

    @field_validator("categories")
    @classmethod
    def unique_categories(cls, value: list[CategoryCode]) -> list[CategoryCode]:
        if len(value) != len(set(value)):
            message = "categories must be unique"
            raise ValueError(message)
        return value


class ActivitySummary(ActivityCommon):
    id: UUID
    location_details: PublicLocation


class ActivityWrite(ActivityCommon):
    booking_notes: str | None = None
    accessibility_notes: str | None = None
    location_details: PublicLocationWrite
    availability_schedules: list[ScheduleWrite]

    @field_validator("availability_schedules")
    @classmethod
    def valid_schedules(
        cls, value: list[ScheduleWrite], info: ValidationInfo
    ) -> list[ScheduleWrite]:
        if info.data.get("is_active") and not value:
            message = "active activities require availability_schedules"
            raise ValueError(message)
        identities = [schedule.identity() for schedule in value]
        if len(identities) != len(set(identities)):
            message = "availability_schedules contain a duplicate"
            raise ValueError(message)
        duration = info.data.get("duration_minutes")
        if any(
            duration is not None and schedule.interval_minutes() < duration
            for schedule in value
        ):
            message = "each schedule interval must fit the activity duration"
            raise ValueError(message)
        return value


class ActivityDetail(ActivityCommon):
    id: UUID
    booking_notes: str | None = None
    accessibility_notes: str | None = None
    location_details: PublicLocation
    availability_schedules: list[Schedule]

    @field_validator("availability_schedules")
    @classmethod
    def valid_schedules(
        cls, value: list[Schedule], info: ValidationInfo
    ) -> list[Schedule]:
        if info.data.get("is_active") and not value:
            message = "active activities require availability_schedules"
            raise ValueError(message)
        identities = [schedule.identity() for schedule in value]
        if len(identities) != len(set(identities)):
            message = "availability_schedules contain a duplicate"
            raise ValueError(message)
        duration = info.data.get("duration_minutes")
        if any(
            duration is not None and schedule.interval_minutes() < duration
            for schedule in value
        ):
            message = "each schedule interval must fit the activity duration"
            raise ValueError(message)
        return value


class ActivityPage(StrictModel):
    activities: list[ActivitySummary]
    total: int = Field(ge=0, strict=True)
    limit: int = Field(ge=1, le=100, strict=True)
    offset: int = Field(ge=0, strict=True)


class DeleteResult(StrictModel):
    id: UUID
    deleted: bool = Field(strict=True)


class BackendHealth(StrictModel):
    status: str
    service: str
    database: str
    location: str


class ItinerarySelectionWrite(StrictModel):
    date: dt.date | None = None
    start_time: LocalTime | None = None

    @field_serializer("start_time")
    def serialize_start_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class ItinerarySelection(StrictModel):
    itinerary_id: str
    name: str
    selected: bool = Field(strict=True)
    start_date: dt.date
    end_date: dt.date
    date: dt.date | None = None
    start_time: LocalTime | None = None


class ItineraryPicker(StrictModel):
    itineraries: list[ItinerarySelection]


class TripOption(StrictModel):
    id: str
    name: str
    destination: str
    start_date: dt.date
    end_date: dt.date
    traveller_count: int = Field(ge=1, strict=True)
    status: Literal["draft", "planned", "active", "completed", "cancelled"]
    notes: str | None = None


class TripDirectory(StrictModel):
    available: bool = Field(strict=True)
    trips: list[TripOption] = Field(default_factory=list)


class SearchLocation(StrictModel):
    country: str | None = None
    city: str | None = None
    street: str | None = None


class SearchCategories(StrictModel):
    codes: list[CategoryCode] = Field(min_length=1)
    match: Literal["ANY", "ALL"] = "ANY"


class SearchMoneyRange(StrictModel):
    min: Money | None = None
    max: Money | None = None


class SearchIntegerRange(StrictModel):
    min: int | None = Field(default=None, ge=0, strict=True)
    max: int | None = Field(default=None, ge=0, strict=True)


class SearchAccessibility(StrictModel):
    wheelchair_accessible: bool | None = Field(default=None, strict=True)
    step_free_access: bool | None = Field(default=None, strict=True)
    accessible_toilet: bool | None = Field(default=None, strict=True)


class SearchAvailability(StrictModel):
    date: dt.date
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None

    @field_serializer("start_time", "end_time")
    def serialize_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class ActivityQueryPayload(StrictModel):
    text: str | None = None
    location: SearchLocation | None = None
    categories: SearchCategories | None = None
    price: SearchMoneyRange | None = None
    duration_minutes: SearchIntegerRange | None = None
    party_size: int | None = Field(default=None, ge=1, strict=True)
    youngest_age: int | None = Field(default=None, ge=0, strict=True)
    oldest_age: int | None = Field(default=None, ge=0, strict=True)
    booking_required: bool | None = Field(default=None, strict=True)
    accessibility: SearchAccessibility | None = None
    availability: SearchAvailability | None = None
    sort: Literal[
        "NAME_ASC", "PRICE_ASC", "PRICE_DESC", "DURATION_ASC", "DURATION_DESC"
    ] = "NAME_ASC"
    include_inactive: bool = Field(default=False, strict=True)
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)


class RecommendationPlan(StrictModel):
    question: str
    trip_id: str | None = None
    query: ActivityQueryPayload
    summary: str
    trip_context_available: bool = Field(strict=True)


class RecommendationEvaluationState(StrictModel):
    question: str
    trip_id: str | None = None
    query: ActivityQueryPayload
    summary: str
    attempt: int = Field(ge=1, le=2, strict=True)


class RecommendedActivity(StrictModel):
    reason: str
    activity: ActivityDetail


class RecommendationEvaluation(StrictModel):
    status: Literal["complete", "retry", "no_match"]
    attempt: int = Field(ge=1, le=2, strict=True)
    query: ActivityQueryPayload
    summary: str
    matched_count: int = Field(ge=0, strict=True)
    evaluated_count: int = Field(ge=0, strict=True)
    recommended: list[RecommendedActivity] = Field(default_factory=list)
    overview: str
    considerations: list[str] = Field(default_factory=list)
    disclaimer: str
    revision_explanation: str | None = None
    run_id: str
    model: str
    provider: str
