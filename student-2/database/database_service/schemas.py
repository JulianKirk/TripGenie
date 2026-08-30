"""Request/response models for the database service API.

Separate from `models.py`: those are the ORM tables, these are the wire format
described in ../../docs/database-service-api.md. Keeping them apart means a
column rename does not silently change the contract the backend depends on.

Money is `Decimal` on the way in (exact) and `float` on the way out -- pydantic
serialises `Decimal` as a JSON *string*, and the API doc shows a number.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from database_service.models import (
    AccommodationBookingStatus,
    AccommodationType,
    AvailabilityStatus,
    BedType,
)


class LocationDetailsIn(BaseModel):
    country: str
    city: str
    street: str = ""
    street_number: int | None = None


class RoomDetailsIn(BaseModel):
    room_count: int = Field(ge=0)
    bed_count: int = Field(ge=0)
    bed_types: list[BedType] = Field(default_factory=list)
    description: str = ""


class AccommodationCreate(BaseModel):
    name: str
    type: AccommodationType
    description: str
    price_per_night: Decimal = Field(ge=0)
    availability_status: AvailabilityStatus
    rating: float = Field(default=0.0, ge=0, le=5)
    amenities: list[str] = Field(default_factory=list)
    location_details: LocationDetailsIn
    room_details: RoomDetailsIn | None = None


class AccommodationUpdate(BaseModel):
    """Every field optional -- omitted ones are left unchanged. `None` is not a
    way to clear a field; it is indistinguishable from "not supplied" here.
    """

    name: str | None = None
    type: AccommodationType | None = None
    description: str | None = None
    price_per_night: Decimal | None = Field(default=None, ge=0)
    availability_status: AvailabilityStatus | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    amenities: list[str] | None = None
    location_details: LocationDetailsIn | None = None
    room_details: RoomDetailsIn | None = None


class AccommodationQuery(BaseModel):
    country: str | None = None
    city: str | None = None
    min_room_count: int | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _city_needs_country(self) -> AccommodationQuery:
        if self.city is not None and self.country is None:
            message = "city requires country"
            raise ValueError(message)
        return self


class LocationDetailsOut(BaseModel):
    country: str
    city: str
    street: str
    street_number: int | None


class RoomDetailsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_count: int
    bed_count: int
    bed_types: list[BedType]
    description: str


class AccommodationOut(BaseModel):
    id: UUID
    name: str
    type: AccommodationType
    description: str
    price_per_night: float
    availability_status: AvailabilityStatus
    rating: float
    amenities: list[str]
    location_details: LocationDetailsOut
    room_details: RoomDetailsOut | None


class LocationSummary(BaseModel):
    country: str
    city: str


class AccommodationSummary(BaseModel):
    """The trimmed shape QUERY returns -- no description, amenities or room
    details, since a result list is for choosing which one to GET in full."""

    id: UUID
    name: str
    type: AccommodationType
    price_per_night: float
    availability_status: AvailabilityStatus
    rating: float
    location_details: LocationSummary


class AccommodationList(BaseModel):
    accommodations: list[AccommodationSummary]
    total: int


class AccommodationCreated(BaseModel):
    id: UUID
    name: str


class BookingCreate(BaseModel):
    owner_id: UUID
    trip_id: UUID
    accommodation_id: UUID
    check_in_date: datetime
    check_out_date: datetime
    num_guests: int = Field(ge=1)
    cost: Decimal = Field(ge=0)
    status: AccommodationBookingStatus = AccommodationBookingStatus.PENDING

    @model_validator(mode="after")
    def _check_out_after_check_in(self) -> BookingCreate:
        if self.check_out_date <= self.check_in_date:
            message = "check_out_date must be after check_in_date"
            raise ValueError(message)
        return self


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    trip_id: UUID
    accommodation_id: UUID
    check_in_date: datetime
    check_out_date: datetime
    num_guests: int
    cost: float
    status: AccommodationBookingStatus


class BookingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    accommodation_id: UUID
    check_in_date: datetime
    check_out_date: datetime
    status: AccommodationBookingStatus


class BookingList(BaseModel):
    bookings: list[BookingSummary]
    total: int


class BookingCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: AccommodationBookingStatus


class RatingCreate(BaseModel):
    accommodation_id: UUID
    user_id: UUID
    score: int = Field(ge=1, le=5)
    comment: str = ""


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    accommodation_id: UUID
    user_id: UUID
    score: int
    comment: str
    created_at: datetime


class RatingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    accommodation_id: UUID
    user_id: UUID
    score: int
    comment: str


class RatingList(BaseModel):
    ratings: list[RatingSummary]
    total: int


class RatingCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    score: int


class Health(BaseModel):
    status: str
    service: str
