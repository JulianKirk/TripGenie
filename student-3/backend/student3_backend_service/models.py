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
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(max_length=2000)]
Price = Annotated[float, Field(ge=0, le=1_000_000)]
UtcOffsetMinutes = Annotated[int, Field(ge=-720, le=840)]

T = TypeVar("T")

MAX_TRANSPORT_DURATION_MINUTES = 60 * 24 * 90
MAX_COMPARE_SELECTION = 4
MAX_AI_RECOMMENDATIONS = 3

_ISO_DATETIME_MESSAGE = "must be a valid ISO timestamp in YYYY-MM-DDTHH:MM format"
_ISO_DATE_MESSAGE = "must be a valid ISO date in YYYY-MM-DD format"
_MONEY_MESSAGE = "must have at most 2 decimal places"


def _validate_iso_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(_ISO_DATE_MESSAGE) from exc

    return value


def _validate_iso_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(_ISO_DATETIME_MESSAGE) from exc

    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError(_ISO_DATETIME_MESSAGE)

    return value


def _validate_money(value: float) -> float:
    rounded = round(value, 2)
    if abs(value - rounded) > 1e-9:
        raise ValueError(_MONEY_MESSAGE)

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


class PricingBasis(str, Enum):
    """Whether `price` multiplies by the party size.

    Mirrors the database service. Not derivable from `type`: a shuttle transfer
    is sold per seat while a car hire of the same capacity is sold per vehicle.
    """

    PER_TRAVELLER = "per_traveller"
    PER_VEHICLE = "per_vehicle"


class PlanStatus(str, Enum):
    """Plan states. TripGenie does not place reservations with carriers."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


ACTIVE_PLAN_STATUSES = frozenset(
    {PlanStatus.PENDING, PlanStatus.CONFIRMED, PlanStatus.COMPLETED},
)


class LenientModel(BaseModel):
    """For payloads another service owns.

    Extra fields are ignored: the itinerary service adding a column must not
    break transport.
    """

    model_config = ConfigDict(extra="ignore")


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


class DeleteResponse(StrictModel):
    id: str
    deleted: bool = True


class DatabaseHealthPayload(StrictModel):
    status: str
    service: str
    sqlite_path: str


class DependencyStatus(StrictModel):
    status: str
    service: str
    detail: str
    code: str | None = None


class HealthDependencies(StrictModel):
    database: DependencyStatus


class HealthResponse(StrictModel):
    status: str
    service: str
    dependencies: HealthDependencies


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


class TransportOptionRecord(TransportOptionFields):
    id: TransportIdentifier
    duration_minutes: int = Field(ge=1, le=MAX_TRANSPORT_DURATION_MINUTES)
    # None means "not known right now", not "none left". The figure is derived
    # from selections held by the itinerary service; when that cannot be
    # reached the honest answer is that the seat count is unavailable, and a
    # page must say so rather than imply a full or empty service.
    seats_remaining: int | None = Field(default=None, ge=0)


class TripTransportPin(LenientModel):
    """One transport selection, as the itinerary service reports it."""

    trip_id: TripIdentifier
    transport_id: TransportIdentifier
    traveller_count: int = Field(ge=1, le=1000)
    plan_status: PlanStatus = PlanStatus.PENDING
    added_on: IsoDate
    notes: LongText | None = None


class TransportTravellerTotal(LenientModel):
    transport_id: TransportIdentifier
    travellers: int = Field(ge=0)


class ItinerarySelection(StrictModel):
    """One trip, and whether this transport option is part of it.

    Shaped for a tick-list: the UI shows every trip a traveller has and marks
    the ones already carrying this option, so choosing is recognition rather
    than recall.
    """

    trip_id: TripIdentifier
    name: ShortText
    destination: ShortText
    start_date: IsoDate
    end_date: IsoDate
    selected: bool = False
    traveller_count: int | None = Field(default=None, ge=1, le=1000)
    plan_status: PlanStatus | None = None
    estimated_cost: Price | None = None


class ItinerarySelectionRequest(StrictModel):
    """What a caller sends when attaching transport to a trip.

    No date: the option already carries its departure and arrival. No cost
    either -- that is derived from the price and the party size, so accepting
    one would let a caller state a total that contradicts the option.
    """

    traveller_count: int = Field(ge=1, le=1000)
    plan_status: PlanStatus = PlanStatus.PENDING
    notes: LongText | None = None

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class ItinerarySelectionResponse(StrictModel):
    transport_id: TransportIdentifier
    currency: CurrencyCode
    seats_remaining: int | None = Field(default=None, ge=0)
    itineraries: list[ItinerarySelection] = Field(default_factory=list)


class TripSummary(BaseModel):
    """A trip as Student 1 reports it. Extra fields are tolerated on purpose.

    Student 1 owns trips; this exists only so pickers can show a readable label
    instead of asking a traveller to type a raw identifier.
    """

    model_config = ConfigDict(extra="ignore")

    id: TripIdentifier
    name: ShortText
    destination: ShortText
    start_date: IsoDate
    end_date: IsoDate
    status: str | None = None


class TripDirectory(StrictModel):
    """Trips available for selection, and whether the lookup succeeded.

    ``available`` is false when Student 1's service could not be reached, which
    lets a caller fall back to free text instead of showing an empty picker that
    looks like "you have no trips".
    """

    available: bool
    trips: list[TripSummary]


class TransportRecommendationRequest(StrictModel):
    """What a traveller is asking for. Route and trip are both optional.

    Supplying a trip narrows the candidates to that trip's existing plan
    context; supplying a route narrows them to matching options. With neither,
    the whole catalogue (capped) is offered as context.
    """

    trip_id: TripIdentifier | None = None
    origin: ShortText | None = None
    destination: ShortText | None = None
    question: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @field_validator("origin", "destination", "question")
    @classmethod
    def normalise_text(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TransportSuggestion(StrictModel):
    """One suggested option. The identifier must be one that was offered."""

    transport_id: Annotated[
        str,
        Field(
            description=(
                "The id of one candidate transport option, copied exactly from "
                "the supplied candidates. Never invent an id."
            ),
        ),
    ]
    reason: Annotated[
        str,
        StringConstraints(min_length=1, max_length=240),
        Field(
            description=(
                "Why this option suits the request, quoting exact supplied "
                "duration, price or seat figures."
            ),
        ),
    ]


class TransportRecommendationDraft(StrictModel):
    """The model's advisory output. Nothing here is saved automatically."""

    overview: Annotated[
        str,
        StringConstraints(min_length=1, max_length=400),
        Field(
            description=(
                "A concise direct answer quoting at least one exact supplied "
                "figure, and stating any uncertainty honestly."
            ),
        ),
    ]
    suggestions: list[TransportSuggestion] = Field(
        min_length=1,
        max_length=MAX_AI_RECOMMENDATIONS,
    )
    considerations: list[
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=180),
            Field(description="One trade-off supported by the supplied context."),
        ]
    ] = Field(default_factory=list, max_length=MAX_AI_RECOMMENDATIONS)
    disclaimer: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class RecommendedTransport(StrictModel):
    """A suggestion resolved back to the real option record it names."""

    reason: str
    option: TransportOptionRecord


class TransportRecommendationResponse(StrictModel):
    """Draft advice plus provenance. Advisory only: the traveller saves it."""

    overview: str
    recommended: list[RecommendedTransport]
    considerations: list[str]
    disclaimer: str
    advisory_only: bool = True
    run_id: str
    model: str
    provider: str


class PlannedTransport(StrictModel):
    """One selection joined to the transport option it refers to.

    `estimated_cost` is derived here rather than stored anywhere: the itinerary
    service holds the party size and this service holds the price, and only
    this side knows whether that price is per traveller or per vehicle.
    """

    entry: TripTransportPin
    option: TransportOptionRecord
    estimated_cost: Price


class TripTransportSummary(StrictModel):
    trip_id: TripIdentifier
    currency: CurrencyCode
    entry_count: int = Field(ge=0)
    active_entry_count: int = Field(ge=0)
    estimated_cost_total: Price
    planned: list[PlannedTransport]
