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

from decimal import Decimal
from typing import Literal
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


class LocationCreateRequest(Location):
    """The same message with the two names a new accommodation cannot go
    without. The database service stores both as NOT NULL ids, so requiring
    them here turns what would be its 400 into one raised before the round
    trip -- and /docs then documents the create contract."""

    country: str = Field(min_length=1)
    city: str = Field(min_length=1)


class AccommodationCreateRequest(Accommodation):
    """The body of POST /accommodation.

    Mirrors the database service's create request, with places named rather
    than identified -- the route translates the two names into ids on the way
    through. `id` is not accepted: the database service mints it.
    """

    model_config = ConfigDict(extra="forbid")

    id: None = None
    name: str = Field(min_length=1)
    type: AccommodationType
    description: str = Field(min_length=1)
    price_per_night: float = Field(ge=0)
    availability_status: AvailabilityStatus
    location_details: LocationCreateRequest


class AccommodationUpdateRequest(Accommodation):
    """The body of PUT /accommodation/{id} -- a merge, so every field is
    optional and an omitted one is left alone. There is no way to unset a
    field, the same as the database service's PUT.

    `id` comes from the path; accepting a second one in the body would only
    invite the two to disagree.
    """

    id: None = None

    @model_validator(mode="after")
    def _city_needs_country(self) -> AccommodationUpdateRequest:
        # Same rule as a search: "Sydney" alone names more than one place, and
        # the location client cannot resolve a city without its country.
        location = self.location_details
        if location is not None and location.city and not location.country:
            message = "city requires country"
            raise ValueError(message)
        return self


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


class AiSearchRequest(BaseModel):
    """A question in English, plus the same paging every search takes.

    `limit` and `offset` are the caller's, never the model's -- the pager on the
    page has to keep working after an AI search, and it knows nothing about how
    the filters were arrived at.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AiSearchAnswer(AccommodationQueryRequest):
    """What the model is asked for: the filters, plus a sentence for the reader.

    One call, one answer. `reply` is the model saying back what it took the
    question to mean, in the traveller's own terms -- the filters underneath say
    the same thing in field names, which is precise and unfriendly.

    ponytail: written before any row is fetched, so it can restate the question
    but cannot describe the results ("the cheapest is $80"). A second call with
    the rows in the prompt would buy that, at the cost of doubling the wait on a
    local model. Do that when someone asks for it.
    """

    reply: str = Field(min_length=1, max_length=300)


class AiSearchResponse(AccommodationQueryResponse):
    """The rows, and the search that produced them.

    `query_used` is the whole point of returning more than a result list: it is
    a plain `AccommodationQueryRequest`, so a caller can show what the question
    was understood to mean, and re-run or edit it as an ordinary QUERY without
    going near the model again.
    """

    query_used: AccommodationQueryRequest
    reply: str


class ItinerarySelection(BaseModel):
    """One of student 1's itineraries, and whether this accommodation is on it.

    `selected` is what the picker draws as ticked or unticked; the frontend
    needs no second call to work it out.

    `start_date` and `end_date` are the itinerary's own window. They are here
    so the page can bound its date inputs to it -- a stay outside the trip is
    rejected by student 1, and an input that cannot offer the date beats an
    error that explains it afterwards.

    `check_in`/`check_out` are the stored stay, present only on a selected
    itinerary and only when student 1 could be asked for it.
    """

    model_config = ConfigDict(extra="forbid")

    itinerary_id: str
    name: str
    selected: bool
    start_date: str
    end_date: str
    check_in: str | None = None
    check_in_time: str | None = None
    check_out: str | None = None
    check_out_time: str | None = None


class StayDates(BaseModel):
    """The body of a PUT that pins an accommodation to an itinerary.

    Both optional: student 1 defaults a missing check-in to the trip's first
    day, which is what this endpoint did before a user could pick one.

    ponytail: no ordering or window check here. Student 1 owns those rules --
    it is the service that stores the row -- and its 422 relays through
    `client.request` as a message this service can show.
    """

    model_config = ConfigDict(extra="forbid")

    check_in: str | None = None
    check_in_time: str | None = None
    check_out: str | None = None
    check_out_time: str | None = None


class AccommodationCostItem(BaseModel):
    item_id: UUID
    description: str
    status: Literal["planned"] = "planned"
    amount: Decimal = Field(ge=0, decimal_places=2)
    currency: Literal["AUD"] = "AUD"


class AccommodationCostResponse(BaseModel):
    committed_cost_total: Decimal = Field(ge=0, decimal_places=2)
    currency: Literal["AUD"] = "AUD"
    items: list[AccommodationCostItem]


class ItinerarySelectionResponse(BaseModel):
    itineraries: list[ItinerarySelection]


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
    location: str
    # "not_configured" when the ask box is switched off, which is a healthy
    # answer -- see routers/health.py.
    ai_mode: str
