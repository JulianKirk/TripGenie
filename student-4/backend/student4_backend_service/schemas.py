from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Generic, Literal, Self, TypeVar
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
        message = "must be a canonical decimal string with two places"
        raise ValueError(message)
    return Decimal(value)


Money = Annotated[
    Decimal,
    BeforeValidator(_money),
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str),
]


def _local_time(value: object) -> dt.time:
    if isinstance(value, dt.time):
        if value.second == 0 and value.microsecond == 0 and value.tzinfo is None:
            return value
        message = "must use local HH:MM format"
        raise ValueError(message)
    if not isinstance(value, str) or TIME_PATTERN.fullmatch(value) is None:
        message = "must use local HH:MM format"
        raise ValueError(message)
    return dt.time.fromisoformat(value)


LocalTime = Annotated[dt.time, BeforeValidator(_local_time)]
PricingBasis = Literal["PER_PERSON", "FLAT_ADMISSION"]
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
DayOfWeek = Literal[
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicLocationWrite(StrictModel):
    country: str
    city: str
    street: str | None = None
    street_number: int | None = Field(default=None, ge=0, strict=True)


class PublicLocation(StrictModel):
    country: str | None = None
    city: str | None = None
    street: str | None = None
    street_number: int | None = Field(default=None, ge=0, strict=True)


class InternalLocation(StrictModel):
    country_id: UUID
    city_id: UUID
    street: str | None = None
    street_number: int | None = Field(default=None, ge=0, strict=True)


class InternalLocationRecord(InternalLocation):
    id: UUID


class Schedule(StrictModel):
    recurring_weekly: bool = Field(strict=True)
    day_of_week: DayOfWeek | None = None
    date: dt.date | None = None
    start_time: LocalTime
    end_time: LocalTime

    @field_serializer("start_time", "end_time")
    def serialise_time(self, value: dt.time) -> str:
        return value.strftime("%H:%M")

    @model_validator(mode="after")
    def valid_rule(self) -> Self:
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

    def identity(
        self,
    ) -> tuple[bool, DayOfWeek | None, dt.date | None, dt.time, dt.time]:
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


class ScheduleRecord(Schedule):
    id: UUID


class ActivityFields(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    price: Money
    pricing_basis: PricingBasis
    duration_minutes: int = Field(gt=0, strict=True)
    minimum_age: int | None = Field(default=None, ge=0, strict=True)
    maximum_age: int | None = Field(default=None, ge=0, strict=True)
    minimum_participants: int = Field(ge=1, strict=True)
    maximum_participants: int | None = Field(default=None, ge=1, strict=True)
    booking_required: bool = Field(default=False, strict=True)
    booking_notes: str | None = None
    wheelchair_accessible: bool | None = Field(default=None, strict=True)
    step_free_access: bool | None = Field(default=None, strict=True)
    accessible_toilet: bool | None = Field(default=None, strict=True)
    accessibility_notes: str | None = None
    is_active: bool = Field(default=True, strict=True)
    categories: list[CategoryCode] = Field(min_length=1)
    availability_schedules: Sequence[Schedule]

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

    @field_validator("availability_schedules")
    @classmethod
    def valid_schedules(
        cls, value: Sequence[Schedule], info: ValidationInfo
    ) -> Sequence[Schedule]:
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


class ActivityWrite(ActivityFields):
    location_details: PublicLocationWrite


class InternalActivityWrite(ActivityFields):
    location_details: InternalLocation


class InternalActivity(InternalActivityWrite):
    id: UUID
    location_details: InternalLocationRecord
    availability_schedules: list[ScheduleRecord]


class Activity(ActivityFields):
    id: UUID
    location_details: PublicLocation
    availability_schedules: list[ScheduleRecord]


class SummaryFields(StrictModel):
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


class InternalSummary(SummaryFields):
    id: UUID
    location_details: InternalLocation


class ActivitySummary(SummaryFields):
    id: UUID
    location_details: PublicLocation


class LocationFilter(StrictModel):
    country: str | None = None
    city: str | None = None
    street: str | None = None

    @model_validator(mode="after")
    def city_needs_country(self) -> Self:
        if self.city and not self.country:
            message = "city requires country"
            raise ValueError(message)
        return self


class CategoryFilter(StrictModel):
    codes: list[CategoryCode] = Field(min_length=1)
    match: Literal["ANY", "ALL"] = "ANY"

    @field_validator("codes")
    @classmethod
    def unique_codes(cls, value: list[CategoryCode]) -> list[CategoryCode]:
        if len(value) != len(set(value)):
            message = "category codes must be unique"
            raise ValueError(message)
        return value


class MoneyRange(StrictModel):
    min: Money | None = None
    max: Money | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            message = "min must not exceed max"
            raise ValueError(message)
        return self


class IntegerRange(StrictModel):
    min: int | None = Field(default=None, ge=0, strict=True)
    max: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            message = "min must not exceed max"
            raise ValueError(message)
        return self


class AccessibilityFilter(StrictModel):
    wheelchair_accessible: bool | None = Field(default=None, strict=True)
    step_free_access: bool | None = Field(default=None, strict=True)
    accessible_toilet: bool | None = Field(default=None, strict=True)


class AvailabilityFilter(StrictModel):
    date: dt.date
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None

    @field_serializer("start_time", "end_time")
    def serialise_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None

    @model_validator(mode="after")
    def complete_window(self) -> Self:
        if (self.start_time is None) != (self.end_time is None):
            message = "start_time and end_time must be supplied together"
            raise ValueError(message)
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            message = "start_time must precede end_time"
            raise ValueError(message)
        return self


class ActivityQuery(StrictModel):
    text: str | None = None
    location: LocationFilter | None = None
    categories: CategoryFilter | None = None
    price: MoneyRange | None = None
    duration_minutes: IntegerRange | None = None
    party_size: int | None = Field(default=None, ge=1, strict=True)
    youngest_age: int | None = Field(default=None, ge=0, strict=True)
    oldest_age: int | None = Field(default=None, ge=0, strict=True)
    booking_required: bool | None = None
    accessibility: AccessibilityFilter | None = None
    availability: AvailabilityFilter | None = None
    sort: Literal[
        "NAME_ASC", "PRICE_ASC", "PRICE_DESC", "DURATION_ASC", "DURATION_DESC"
    ] = "NAME_ASC"
    include_inactive: bool = Field(default=False, strict=True)
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def ages_are_ordered(self) -> Self:
        if (
            self.youngest_age is not None
            and self.oldest_age is not None
            and self.youngest_age > self.oldest_age
        ):
            message = "youngest_age must not exceed oldest_age"
            raise ValueError(message)
        return self


class InternalQueryResponse(StrictModel):
    activities: list[InternalSummary]
    total: int = Field(ge=0, strict=True)
    limit: int = Field(ge=1, le=100, strict=True)
    offset: int = Field(ge=0, strict=True)


class QueryResponse(StrictModel):
    activities: list[ActivitySummary]
    total: int = Field(ge=0, strict=True)
    limit: int = Field(ge=1, le=100, strict=True)
    offset: int = Field(ge=0, strict=True)


class CategoryRecord(StrictModel):
    code: CategoryCode
    label: str
    description: str | None = None
    display_order: int = Field(ge=0, strict=True)


class CategoryList(StrictModel):
    categories: list[CategoryRecord]


class DeleteResponse(StrictModel):
    id: UUID
    deleted: bool = Field(strict=True)


class HealthResponse(StrictModel):
    status: str
    service: str
    database: str
    location: str


class ActivitySchedule(StrictModel):
    date: dt.date | None = None
    start_time: LocalTime | None = None

    @field_serializer("start_time")
    def serialise_start_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class ItinerarySelection(StrictModel):
    itinerary_id: str
    name: str
    selected: bool
    start_date: dt.date
    end_date: dt.date
    date: dt.date | None = None
    start_time: LocalTime | None = None

    @field_serializer("start_time")
    def serialise_start_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class ItinerarySelectionResponse(StrictModel):
    itineraries: list[ItinerarySelection]


T = TypeVar("T")


class DataEnvelope(StrictModel, Generic[T]):
    data: T


class StudentErrorDetail(StrictModel):
    field: str = Field(min_length=1)
    issue: str = Field(min_length=1)

    @field_validator("field", "issue")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            message = "must not be blank"
            raise ValueError(message)
        return value.strip()


class StudentErrorBody(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: list[StudentErrorDetail]

    @field_validator("code", "message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            message = "must not be blank"
            raise ValueError(message)
        return value.strip()


class StudentErrorEnvelope(StrictModel):
    error: StudentErrorBody


class ItineraryTrip(StrictModel):
    id: str
    name: str
    destination: str
    start_date: dt.date
    end_date: dt.date
    traveller_count: int = Field(ge=1, strict=True)
    status: Literal["draft", "planned", "active", "completed", "cancelled"]
    notes: str | None = None


class TripActivityWire(StrictModel):
    trip_id: str
    activity_id: str
    date: dt.date
    start_time: LocalTime | None = None


class ActivityCostItem(StrictModel):
    item_id: UUID
    description: str = Field(min_length=1)
    status: Literal["planned"] = "planned"
    amount: Money
    currency: Literal["AUD"] = "AUD"


class ActivityCostResponse(StrictModel):
    committed_cost_total: Money
    currency: Literal["AUD"] = "AUD"
    items: list[ActivityCostItem]


class StudentDeleteResponse(StrictModel):
    id: str
    deleted: bool = Field(strict=True)


class DependencyHealth(StrictModel):
    status: str
    service: str | None = None


class CountryRecord(StrictModel):
    id: UUID
    name: str


class CityRecord(StrictModel):
    id: UUID
    name: str
    country_id: UUID


class CountryPage(StrictModel):
    countries: list[CountryRecord]
    total: int = Field(ge=0, strict=True)


class CityPage(StrictModel):
    cities: list[CityRecord]
    total: int = Field(ge=0, strict=True)
