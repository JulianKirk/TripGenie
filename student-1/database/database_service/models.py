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
# Activity ids are minted by Student 4. Keep the same cross-service boundary as
# accommodation ids: Student 1 stores an opaque, bounded identifier.
ActivityIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]
# Transport ids are minted by Student 3. Same cross-service boundary as
# accommodation and activity ids: an opaque, bounded identifier.
TransportIdentifier = Annotated[
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


def _normalise_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TripStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TripTransportStatus(str, Enum):
    """Plan states for a transport selection.

    TripGenie does not book transport, so these describe where a chosen option
    sits in the traveller's plan, not anything agreed with a carrier.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


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


class HealthResponse(StrictModel):
    status: str
    service: str
    sqlite_path: str


class DeleteResponse(StrictModel):
    id: str
    deleted: bool = True


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

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TripCreate(TripFields):
    id: TripIdentifier | None = None


class TripUpdate(StrictModel):
    name: ShortText | None = None
    destination: ShortText | None = None
    start_date: IsoDate | None = None
    end_date: IsoDate | None = None
    traveller_count: int | None = Field(default=None, ge=1, le=1000)
    status: TripStatus | None = None
    notes: LongText | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return _validate_iso_date(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


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


class TripAccommodationCreate(StrictModel):
    """The body of a PUT that pins an accommodation to a trip -- the stay
    window; both ids are in the path.

    `date` stays required here. This service's only caller is the backend,
    which always resolves a check-in before calling -- defaulting it to the
    trip's first day when the user did not pick one. Making it optional would
    only let a None reach a NOT NULL column.
    """

    date: IsoDate
    check_in_time: IsoTime | None = None
    check_out: IsoDate | None = None
    check_out_time: IsoTime | None = None

    @field_validator("date", "check_out")
    @classmethod
    def validate_trip_accommodation_create_date(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_date(value)

    @field_validator("check_in_time", "check_out_time")
    @classmethod
    def validate_trip_accommodation_create_time(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_time(value)

    @model_validator(mode="after")
    def validate_stay_order(self) -> TripAccommodationCreate:
        if self.check_out is not None and self.check_out < self.date:
            raise ValueError("check_out must be on or after date")
        return self


class TripActivityRecord(StrictModel):
    """One Student 4 activity selected for one Student 1 trip."""

    trip_id: TripIdentifier
    activity_id: ActivityIdentifier
    date: IsoDate
    start_time: IsoTime | None = None

    @field_validator("date")
    @classmethod
    def validate_activity_date(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("start_time")
    @classmethod
    def validate_activity_time(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_time(value)


class TripActivityCreate(StrictModel):
    """Resolved activity selection sent by the Student 1 backend."""

    date: IsoDate
    start_time: IsoTime | None = None

    @field_validator("date")
    @classmethod
    def validate_activity_date(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("start_time")
    @classmethod
    def validate_activity_time(cls, value: str | None) -> str | None:
        return value if value is None else _validate_iso_time(value)



class TripTransportRecord(StrictModel):
    """One Student 3 transport option selected for one Student 1 trip.

    There is no date column, unlike the accommodation and activity links: a
    transport option already carries its own departure and arrival times, and
    a second date stored here could only ever disagree with them.

    `traveller_count` is stored because Student 3 prices per traveller and
    cannot work the figure out from the trip alone -- transport may be chosen
    for some of the party rather than all of it. Cost itself is not stored: it
    is Student 3's to derive from its own prices.
    """

    trip_id: TripIdentifier
    transport_id: TransportIdentifier
    traveller_count: int = Field(ge=1, le=1000)
    plan_status: TripTransportStatus = TripTransportStatus.PENDING
    added_on: IsoDate
    notes: LongText | None = None

    @field_validator("added_on")
    @classmethod
    def validate_added_on(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class TransportTravellerTotal(StrictModel):
    """Travellers pinned to one transport option, across every trip.

    Exists so Student 3 can derive `seats_remaining` in one request instead of
    one per option.
    """

    transport_id: TransportIdentifier
    travellers: int = Field(ge=0)


class TripTransportCreate(StrictModel):
    """A transport selection sent by the Student 1 backend."""

    traveller_count: int = Field(ge=1, le=1000)
    plan_status: TripTransportStatus = TripTransportStatus.PENDING
    added_on: IsoDate
    notes: LongText | None = None

    @field_validator("added_on")
    @classmethod
    def validate_added_on(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("notes")
    @classmethod
    def normalise_notes(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


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

    @field_validator("location", "description", "notes")
    @classmethod
    def normalise_optional_fields(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class ItineraryItemCreate(ItineraryItemFields):
    id: ItemIdentifier | None = None


class ItineraryItemUpdate(StrictModel):
    date: IsoDate | None = None
    start_time: IsoTime | None = None
    end_time: IsoTime | None = None
    title: ShortText | None = None
    location: ShortText | None = None
    description: LongText | None = None
    category: ItineraryCategory | None = None
    notes: LongText | None = None

    @field_validator("date")
    @classmethod
    def validate_item_date(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return _validate_iso_date(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_item_time(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return _validate_iso_time(value)

    @field_validator("location", "description", "notes")
    @classmethod
    def normalise_optional_fields(cls, value: str | None) -> str | None:
        return _normalise_optional_text(value)


class ItineraryItemRecord(ItineraryItemFields):
    id: ItemIdentifier
    trip_id: TripIdentifier
