"""The wire format this service publishes -- the accommodation contract.

These mirror `database_service/schemas.py`, deliberately duplicated rather than
imported. This service is the public face: the frontend and the other students'
backends code against what *it* documents and serves at /docs, and they cannot
reach the internal service that would otherwise own the shape. Importing it
would also put the database package inside this image, so the two would stop
being independently deployable.

The cost is a second representation. When the database service adds a field,
`extra="forbid"` makes parsing its response fail and the route returns the
documented 502 -- a loud failure, not a silent one, and the end-to-end tests in
tests/e2e run the real database app, so drift breaks CI immediately. Add
the field here to fix it.

One message, nullable fields -- the protobuf convention, same as the database
service. `Accommodation` is both the search template and every response body;
which fields are populated is what differs, and routes serialise with
`response_model_exclude_none=True` so an unset field is absent rather than null.

`price_per_night` is a float here, not the database service's `Decimal`. This
service does no arithmetic on money, it relays it, and the database service
already serialises the field as a JSON number.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend_service.enums import AccommodationType, AvailabilityStatus, BedType


class Location(BaseModel):
    """Where an accommodation is."""

    model_config = ConfigDict(extra="forbid")

    country: str | None = None
    city: str | None = None
    street: str | None = None
    street_number: int | None = None


class Room(BaseModel):
    """What you get to sleep in."""

    model_config = ConfigDict(extra="forbid")

    room_count: int | None = Field(default=None, ge=0)
    bed_count: int | None = Field(default=None, ge=0)
    bed_types: list[BedType] | None = None
    description: str | None = None


class Accommodation(BaseModel):
    """The accommodation message. Every field is nullable because the same
    class carries a search template and every response."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    name: str | None = None
    type: AccommodationType | None = None
    description: str | None = None
    price_per_night: float | None = Field(default=None, ge=0)
    availability_status: AvailabilityStatus | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    amenities: list[str] | None = None
    location_details: Location | None = None
    room_details: Room | None = None


class AccommodationQueryRequest(BaseModel):
    """A match template plus the bounds that a template cannot express.

    Forwarded to the database service as-is; its QUERY documents the template
    in full. Validated here so a malformed search is a 400 without a round
    trip, and so /docs describes the search this service accepts.
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
    database: str
