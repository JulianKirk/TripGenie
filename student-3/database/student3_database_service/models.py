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


class PricingBasis(str, Enum):
    """Whether `price` multiplies by the party size.

    Not derivable from `type`: the seeded ski shuttle is a transfer sold per
    seat, while a car hire of the same capacity is sold per vehicle. A consumer
    that guessed from the type would overstate a hire by the traveller count,
    so this is stored per option rather than inferred.
    """

    PER_TRAVELLER = "per_traveller"
    PER_VEHICLE = "per_vehicle"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    LIMITED = "limited"
    SOLD_OUT = "sold_out"
    CANCELLED = "cancelled"


BOOKABLE_AVAILABILITY_STATUSES = frozenset(
    {AvailabilityStatus.AVAILABLE, AvailabilityStatus.LIMITED},
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
    pricing_basis: PricingBasis = PricingBasis.PER_TRAVELLER
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
    pricing_basis: PricingBasis | None = None
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
    """What this service returns for an option.

    Identical to the stored shape. `seats_remaining` used to live here, derived
    from a selections table this service owned; selections now belong to the
    itinerary service, so the backend derives the seat count instead. The name
    is kept so callers that read a "record" still have one.
    """


