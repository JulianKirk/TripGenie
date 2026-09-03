from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

TransportIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=11,
        max_length=64,
        pattern=r"^transport_[A-Za-z0-9][A-Za-z0-9_-]{2,53}$",
    ),
]
BookingIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=9,
        max_length=64,
        pattern=r"^booking_[A-Za-z0-9][A-Za-z0-9_-]{2,55}$",
    ),
]
TripIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=6,
        max_length=64,
        pattern=r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$",
    ),
]
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
IsoDateTime = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"),
]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(max_length=2000)]
Price = Annotated[float, Field(ge=0, le=1_000_000)]
# UTC-12:00 through UTC+14:00, the range of real civil offsets.
UtcOffsetMinutes = Annotated[int, Field(ge=-720, le=840)]

T = TypeVar("T")

MAX_TRANSPORT_DURATION_MINUTES = 60 * 24 * 90


def _validate_iso_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be a valid ISO date in YYYY-MM-DD format") from exc

    return value


def _validate_iso_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "must be a valid ISO timestamp in YYYY-MM-DDTHH:MM format",
        ) from exc

    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError(
            "must be a valid ISO timestamp in YYYY-MM-DDTHH:MM format",
        )

    return value


def _validate_money(value: float) -> float:
    rounded = round(value, 2)
    if abs(value - rounded) > 1e-9:
        raise ValueError("must have at most 2 decimal places")

    return rounded


def _normalise_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TransportType(str, Enum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"
    FERRY = "ferry"
    CAR_RENTAL = "car_rental"
    TRANSFER = "transfer"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    LIMITED = "limited"
    SOLD_OUT = "sold_out"
    CANCELLED = "cancelled"


class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


BOOKABLE_AVAILABILITY_STATUSES = frozenset(
    {AvailabilityStatus.AVAILABLE, AvailabilityStatus.LIMITED},
)
CAPACITY_CONSUMING_BOOKING_STATUSES = frozenset(
    {BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED},
)


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


class HealthResponse(StrictModel):
    status: str
    service: str
    sqlite_path: str


class DeleteResponse(StrictModel):
    id: str
    deleted: bool = True


class TransportOptionFields(StrictModel):
    type: TransportType
    provider: ShortText
    origin: ShortText
    destination: ShortText
    departure_time: IsoDateTime
    arrival_time: IsoDateTime
    departure_utc_offset: UtcOffsetMinutes | None = None
    arrival_utc_offset: UtcOffsetMinutes | None = None
    price: Price
    capacity: int = Field(ge=1, le=10_000)
    availability_status: AvailabilityStatus
    notes: LongText | None = None

    @field_validator("departure_time", "arrival_time")
    @classmethod
    def validate_timestamps(cls, value: str) -> str:
        return _validate_iso_datetime(value)

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: float) -> float:
        return _validate_money(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TransportOptionCreate(TransportOptionFields):
    id: TransportIdentifier | None = None


class TransportOptionUpdate(StrictModel):
    type: TransportType | None = None
    provider: ShortText | None = None
    origin: ShortText | None = None
    destination: ShortText | None = None
    departure_time: IsoDateTime | None = None
    arrival_time: IsoDateTime | None = None
    departure_utc_offset: UtcOffsetMinutes | None = None
    arrival_utc_offset: UtcOffsetMinutes | None = None
    price: Price | None = None
    capacity: int | None = Field(default=None, ge=1, le=10_000)
    availability_status: AvailabilityStatus | None = None
    notes: LongText | None = None

    @field_validator("departure_time", "arrival_time")
    @classmethod
    def validate_timestamps(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return _validate_iso_datetime(value)

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: float | None) -> float | None:
        if value is None:
            return None

        return _validate_money(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TransportOptionStored(TransportOptionFields):
    """Exactly the columns persisted in ``transport_options``."""

    id: TransportIdentifier
    duration_minutes: int = Field(ge=1, le=MAX_TRANSPORT_DURATION_MINUTES)


class TransportOptionRecord(TransportOptionStored):
    """A stored option plus the seat count derived from live bookings."""

    seats_remaining: int = Field(ge=0)


class TransportBookingFields(StrictModel):
    trip_id: TripIdentifier
    transport_id: TransportIdentifier
    traveller_count: int = Field(ge=1, le=1000)
    booking_date: IsoDate
    booking_status: BookingStatus
    notes: LongText | None = None

    @field_validator("booking_date")
    @classmethod
    def validate_booking_date(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TransportBookingCreate(TransportBookingFields):
    id: BookingIdentifier | None = None
    estimated_cost: Price | None = None

    @field_validator("estimated_cost")
    @classmethod
    def validate_estimated_cost(cls, value: float | None) -> float | None:
        if value is None:
            return None

        return _validate_money(value)


class TransportBookingUpdate(StrictModel):
    trip_id: TripIdentifier | None = None
    transport_id: TransportIdentifier | None = None
    traveller_count: int | None = Field(default=None, ge=1, le=1000)
    booking_date: IsoDate | None = None
    booking_status: BookingStatus | None = None
    estimated_cost: Price | None = None
    notes: LongText | None = None

    @field_validator("estimated_cost")
    @classmethod
    def validate_estimated_cost(cls, value: float | None) -> float | None:
        if value is None:
            return None

        return _validate_money(value)

    @field_validator("booking_date")
    @classmethod
    def validate_booking_date(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return _validate_iso_date(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TransportBookingRecord(TransportBookingFields):
    id: BookingIdentifier
    estimated_cost: Price
