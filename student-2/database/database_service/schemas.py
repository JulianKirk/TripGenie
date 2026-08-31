"""The wire format for the database service API.

Separate from `models.py`: those are the ORM tables, these are the messages
described in ../../docs/database-service-api.md.

One message, nullable fields -- the protobuf convention. `Accommodation` is the
PUT body, the match template inside a QUERY, and the response body for every
endpoint; which fields are populated is what differs. Routes serialise with
`response_model_exclude_none=True`, so an unset field is absent from the JSON
rather than an explicit `null`, and "an accommodation with only the id filled
in" is a legal response instead of a mostly-empty object.

Money is `Decimal` on the way in (exact); the routes serialise it as a JSON
number, matching the API doc.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from database_service.enums import AccommodationType, AvailabilityStatus, BedType


class Location(BaseModel):
    """Where an accommodation is."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    country: str | None = None
    city: str | None = None
    street: str | None = None
    street_number: int | None = None


class Room(BaseModel):
    """What you get to sleep in."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    room_count: int | None = Field(default=None, ge=0)
    bed_count: int | None = Field(default=None, ge=0)
    bed_types: list[BedType] | None = None
    description: str | None = None


class Accommodation(BaseModel):
    """The accommodation message. Every field is nullable because the same
    class carries a create, an edit, a search template and a response."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    name: str | None = None
    type: AccommodationType | None = None
    description: str | None = None
    price_per_night: Decimal | None = Field(default=None, ge=0)
    availability_status: AvailabilityStatus | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    amenities: list[str] | None = None
    location_details: Location | None = None
    room_details: Room | None = None

    @field_serializer("price_per_night")
    def _money_as_number(self, value: Decimal | None) -> float | None:
        """Exact `Decimal` in, JSON number out. Pydantic serialises `Decimal`
        as a *string* by default, and the API doc shows `1.00`."""
        return None if value is None else float(value)

    def summary(self) -> Accommodation:
        """The trimmed form a result list returns: the same message with the
        heavy fields cleared, since a list is for choosing which one to GET in
        full. `exclude_none` on the route drops them from the JSON."""
        location = self.location_details
        return self.model_copy(
            update={
                "description": None,
                "amenities": None,
                "room_details": None,
                "location_details": (
                    None
                    if location is None
                    else Location(country=location.country, city=location.city)
                ),
            }
        )


class AccommodationCreateRequest(Accommodation):
    """The same message with the fields a new accommodation cannot go without.
    The only place a field is required, so `POST {}` fails at the edge with a
    400 naming each one, and OpenAPI still documents the create contract."""

    name: str
    type: AccommodationType
    description: str
    price_per_night: Decimal = Field(ge=0)
    availability_status: AvailabilityStatus
    location_details: Location


class AccommodationQueryRequest(BaseModel):
    """A match template plus the bounds that a template cannot express.

    Every field set on `accommodation` must match exactly; the `*_min`/`*_max`
    fields add the comparisons nobody can write as equality (no one searches
    for a hotel costing exactly $189.50). A new range filter is one field here
    and one line in `AccommodationRepository.search`.
    """

    model_config = ConfigDict(extra="forbid")

    accommodation: Accommodation = Field(default_factory=Accommodation)
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    rating_min: float | None = Field(default=None, ge=0, le=5)
    rating_max: float | None = Field(default=None, ge=0, le=5)
    room_count_min: int | None = Field(default=None, ge=0)
    bed_count_min: int | None = Field(default=None, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _city_needs_country(self) -> AccommodationQueryRequest:
        # Sydney exists in more than one country, so a bare city is ambiguous.
        location = self.accommodation.location_details
        if location is not None and location.city and not location.country:
            message = "city requires country"
            raise ValueError(message)
        return self


class AccommodationQueryResponse(BaseModel):
    accommodations: list[Accommodation]
    total: int


class HealthResponse(BaseModel):
    status: str
    service: str
