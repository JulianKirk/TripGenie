from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Annotated, Generic, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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
# An accommodation id is minted by the accommodation service, not here. It is
# a constrained string rather than a UUID on purpose: this service should not
# have to change when another service changes how it mints identifiers.
AccommodationIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
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


class TripAccommodationRecord(StrictModel):
    """One accommodation pinned to one trip -- the associative entity. A trip
    holds many accommodations and an accommodation sits on many trips.

    `date` is the check-in. It kept its name from when it was the only date
    there was, and renaming it is a SQLite table rebuild for no user-visible
    gain. A `check_out` of None means no departure was recorded -- every row
    written before stay dates existed reads that way.
    """

    trip_id: TripIdentifier
    accommodation_id: AccommodationIdentifier
    date: IsoDate
    check_in_time: IsoTime | None = None
    check_out: IsoDate | None = None
    check_out_time: IsoTime | None = None

    @field_validator("date", "check_out")
    @classmethod
    def validate_trip_accommodation_date(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_date(value)

    @field_validator("check_in_time", "check_out_time")
    @classmethod
    def validate_trip_accommodation_time(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_time(value)

    @model_validator(mode="after")
    def validate_stay_order(self) -> TripAccommodationRecord:
        # The table cannot carry this as a CHECK (see the DDL), so it is
        # enforced here, on the one path every read and write goes through.
        # ISO dates and HH:MM times both compare correctly as strings.
        if self.check_out is None:
            return self
        if self.check_out < self.date:
            raise ValueError("check_out must be on or after date")
        # Same day, so the times are what separate arrival from departure.
        if (
            self.check_out == self.date
            and self.check_in_time
            and self.check_out_time
            and self.check_out_time <= self.check_in_time
        ):
            raise ValueError("check_out_time must be after check_in_time")
        return self


class TripAccommodationDetail(TripAccommodationRecord):
    """A pinned accommodation, as the trip page needs to draw it.

    The extra three fields are not stored anywhere: the name and the nightly
    rate belong to student 2, and the total is arithmetic over them and the
    dates here. They are on a subclass rather than on the record itself so the
    write endpoints keep answering with exactly what they stored.

    All three are None when student 2 could not be reached, or when it has no
    price for the accommodation. A trip is still a trip without them.
    """

    name: str | None = None
    price_per_night: float | None = None
    total_price: float | None = None


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
    accommodations: list[TripAccommodationDetail] = Field(
        default_factory=list
    )


class DeleteResponse(StrictModel):
    id: str
    deleted: bool = True


class BackendDependencyPayload(StrictModel):
    status: ShortText
    service: ShortText
    detail: LongText | None = None
    code: ShortText | None = None


class BackendHealthDependencies(StrictModel):
    database: BackendDependencyPayload
    ollama: BackendDependencyPayload


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
