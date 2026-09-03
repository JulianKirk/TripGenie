"""Strict request and response messages for the internal activity API."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    field_validator,
    model_validator,
)

from student4_database_service.enums import (
    ActivitySort,
    CategoryCode,
    CategoryMatch,
    DayOfWeek,
    PricingBasis,
)

MONEY_PATTERN = re.compile(r"^(?:0|[1-9]\d*)\.\d{2}$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SQLITE_INT_MAX = 2**63 - 1


def _parse_money(value: object) -> Decimal:
    if not isinstance(value, str) or MONEY_PATTERN.fullmatch(value) is None:
        message = "must be a canonical non-negative decimal string with two places"
        raise ValueError(message)
    return Decimal(value)


def _serialise_money(value: Decimal) -> str:
    return f"{value:.2f}"


def _parse_local_time(value: object) -> dt.time:
    if not isinstance(value, str) or TIME_PATTERN.fullmatch(value) is None:
        message = "must use local HH:MM format"
        raise ValueError(message)
    return dt.time.fromisoformat(value)


def _serialise_local_time(value: dt.time) -> str:
    return value.strftime("%H:%M")


def _parse_date(value: object) -> dt.date:
    if type(value) is dt.date:
        return value
    if not isinstance(value, str) or DATE_PATTERN.fullmatch(value) is None:
        message = "must use ISO YYYY-MM-DD format"
        raise ValueError(message)
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        message = "must be a valid ISO date"
        raise ValueError(message) from exc
    if parsed.isoformat() != value:
        message = "must use canonical ISO YYYY-MM-DD format"
        raise ValueError(message)
    return parsed


Money = Annotated[
    Decimal,
    BeforeValidator(_parse_money),
    PlainSerializer(_serialise_money, return_type=str),
]
LocalTime = Annotated[
    dt.time,
    BeforeValidator(_parse_local_time),
    PlainSerializer(_serialise_local_time, return_type=str),
]
CanonicalDate = Annotated[dt.date, BeforeValidator(_parse_date)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationWrite(StrictModel):
    country_id: UUID
    city_id: UUID
    street: str | None = None
    street_number: int | None = Field(
        default=None, ge=0, le=SQLITE_INT_MAX, strict=True
    )


class LocationRecord(LocationWrite):
    id: UUID


class LocationSummary(StrictModel):
    country_id: UUID
    city_id: UUID


class ScheduleWrite(StrictModel):
    recurring_weekly: bool = Field(strict=True)
    day_of_week: DayOfWeek | None = None
    date: CanonicalDate | None = None
    start_time: LocalTime
    end_time: LocalTime

    @model_validator(mode="after")
    def validate_recurrence(self) -> Self:
        if self.recurring_weekly:
            if self.day_of_week is None or self.date is not None:
                message = "weekly schedules require day_of_week and forbid date"
                raise ValueError(message)
        elif self.date is None or self.day_of_week is not None:
            message = "one-off schedules require date and forbid day_of_week"
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


class ScheduleRecord(ScheduleWrite):
    id: UUID


class ActivityWrite(StrictModel):
    name: str
    description: str
    price: Money
    pricing_basis: PricingBasis
    duration_minutes: int = Field(gt=0, le=SQLITE_INT_MAX, strict=True)
    minimum_age: int | None = Field(default=None, ge=0, le=SQLITE_INT_MAX, strict=True)
    maximum_age: int | None = Field(default=None, ge=0, le=SQLITE_INT_MAX, strict=True)
    minimum_participants: int = Field(ge=1, le=SQLITE_INT_MAX, strict=True)
    maximum_participants: int | None = Field(
        default=None, ge=1, le=SQLITE_INT_MAX, strict=True
    )
    booking_required: bool = Field(default=False, strict=True)
    booking_notes: str | None = None
    wheelchair_accessible: bool | None = Field(default=None, strict=True)
    step_free_access: bool | None = Field(default=None, strict=True)
    accessible_toilet: bool | None = Field(default=None, strict=True)
    accessibility_notes: str | None = None
    is_active: bool = Field(default=True, strict=True)
    location_details: LocationWrite
    categories: list[CategoryCode] = Field(min_length=1)
    availability_schedules: Sequence[ScheduleWrite]

    @field_validator("name", "description")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            message = "must not be blank"
            raise ValueError(message)
        return value

    @field_validator("categories")
    @classmethod
    def categories_are_unique(
        cls, categories: list[CategoryCode]
    ) -> list[CategoryCode]:
        if len(categories) != len(set(categories)):
            message = "categories must be unique"
            raise ValueError(message)
        return categories

    @field_validator("maximum_age")
    @classmethod
    def age_bounds_are_ordered(
        cls, maximum_age: int | None, info: ValidationInfo
    ) -> int | None:
        minimum_age = info.data.get("minimum_age")
        if (
            minimum_age is not None
            and maximum_age is not None
            and minimum_age > maximum_age
        ):
            message = "maximum_age must be at least minimum_age"
            raise ValueError(message)
        return maximum_age

    @field_validator("maximum_participants")
    @classmethod
    def participant_bounds_are_ordered(
        cls, maximum_participants: int | None, info: ValidationInfo
    ) -> int | None:
        minimum_participants = info.data.get("minimum_participants")
        if (
            minimum_participants is not None
            and maximum_participants is not None
            and minimum_participants > maximum_participants
        ):
            message = "maximum_participants must be at least minimum_participants"
            raise ValueError(message)
        return maximum_participants

    @field_validator("availability_schedules")
    @classmethod
    def schedules_fit_activity(
        cls, schedules: Sequence[ScheduleWrite], info: ValidationInfo
    ) -> Sequence[ScheduleWrite]:
        if info.data.get("is_active") and not schedules:
            message = "active activities require availability_schedules"
            raise ValueError(message)

        identities = [schedule.identity() for schedule in schedules]
        if len(identities) != len(set(identities)):
            message = "availability_schedules contain a duplicate"
            raise ValueError(message)
        duration_minutes = info.data.get("duration_minutes")
        if any(
            duration_minutes is not None
            and schedule.interval_minutes() < duration_minutes
            for schedule in schedules
        ):
            message = "each schedule interval must fit the activity duration"
            raise ValueError(message)
        return schedules


class ActivityRecord(ActivityWrite):
    id: UUID
    location_details: LocationRecord
    availability_schedules: list[ScheduleRecord]


class ActivitySummary(StrictModel):
    id: UUID
    name: str
    description: str
    price: Money
    pricing_basis: PricingBasis
    duration_minutes: int
    minimum_age: int | None = None
    maximum_age: int | None = None
    minimum_participants: int
    maximum_participants: int | None = None
    booking_required: bool
    wheelchair_accessible: bool | None = None
    step_free_access: bool | None = None
    accessible_toilet: bool | None = None
    is_active: bool
    location_details: LocationSummary
    categories: list[CategoryCode]


class LocationFilter(StrictModel):
    country_id: UUID | None = None
    city_id: UUID | None = None
    street: str | None = None


class CategoryFilter(StrictModel):
    codes: list[CategoryCode] = Field(min_length=1)
    match: CategoryMatch = CategoryMatch.ANY

    @field_validator("codes")
    @classmethod
    def codes_are_unique(cls, codes: list[CategoryCode]) -> list[CategoryCode]:
        if len(codes) != len(set(codes)):
            message = "category codes must be unique"
            raise ValueError(message)
        return codes


class MoneyRange(StrictModel):
    min: Money | None = None
    max: Money | None = None

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            message = "min must not exceed max"
            raise ValueError(message)
        return self


class DurationRange(StrictModel):
    min: int | None = Field(default=None, ge=0, le=SQLITE_INT_MAX, strict=True)
    max: int | None = Field(default=None, ge=0, le=SQLITE_INT_MAX, strict=True)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            message = "min must not exceed max"
            raise ValueError(message)
        return self


class AccessibilityFilter(StrictModel):
    wheelchair_accessible: bool | None = Field(default=None, strict=True)
    step_free_access: bool | None = Field(default=None, strict=True)
    accessible_toilet: bool | None = Field(default=None, strict=True)


class AvailabilityFilter(StrictModel):
    date: CanonicalDate
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None

    @model_validator(mode="after")
    def time_window_is_complete(self) -> Self:
        if (self.start_time is None) != (self.end_time is None):
            message = "start_time and end_time must be supplied together"
            raise ValueError(message)
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time >= self.end_time
        ):
            message = "start_time must precede end_time"
            raise ValueError(message)
        return self


class ActivityQueryRequest(StrictModel):
    text: str | None = None
    location_details: LocationFilter | None = None
    categories: CategoryFilter | None = None
    price: MoneyRange | None = None
    duration_minutes: DurationRange | None = None
    party_size: int | None = Field(default=None, ge=1, le=SQLITE_INT_MAX, strict=True)
    youngest_age: int | None = Field(default=None, ge=0, le=SQLITE_INT_MAX, strict=True)
    oldest_age: int | None = Field(default=None, ge=0, le=SQLITE_INT_MAX, strict=True)
    booking_required: bool | None = Field(default=None, strict=True)
    accessibility: AccessibilityFilter | None = None
    availability: AvailabilityFilter | None = None
    is_active: bool | None = Field(default=None, strict=True)
    sort: ActivitySort = ActivitySort.NAME_ASC
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    offset: int = Field(default=0, ge=0, le=SQLITE_INT_MAX, strict=True)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            message = "must not be blank"
            raise ValueError(message)
        return value

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


class ActivityQueryResponse(StrictModel):
    activities: list[ActivitySummary]
    total: int
    limit: int
    offset: int


class CategoryRecord(StrictModel):
    code: CategoryCode
    label: str
    description: str | None = None
    display_order: int = Field(ge=0)


class CategoryListResponse(StrictModel):
    categories: list[CategoryRecord]


class DeleteResponse(StrictModel):
    id: UUID
    deleted: bool


class HealthResponse(StrictModel):
    status: str
    service: str
