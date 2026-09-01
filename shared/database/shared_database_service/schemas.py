"""The wire format for the shared reference database service API.

Separate from `models.py`: those are the ORM tables, these are the messages
described in ../../docs/database-service-api.md.

One message, nullable fields -- the protobuf convention, the same as the
accommodation services. `Country` is the match template inside a QUERY and the
response body for every country endpoint; which fields are populated is what
differs. Routes serialise with `response_model_exclude_none=True`, so an unset
field is absent from the JSON rather than an explicit `null`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Country(BaseModel):
    """A country. Its id is `uuid5` over the name -- see ids.py."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID | None = None
    name: str | None = None


class CountryCreateRequest(Country):
    """The same message with the one field a country cannot go without. The
    only place `name` is required, so `POST {}` fails at the edge with a 400
    naming it, and OpenAPI still documents the create contract."""

    name: str


class City(BaseModel):
    """A city, scoped to a country."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID | None = None
    name: str | None = None
    country_id: UUID | None = None


class CityCreateRequest(City):
    """A city cannot exist without the country it sits in -- the id rule is
    scoped by country, and "Sydney" alone names two places."""

    name: str
    country_id: UUID


class CountryQueryRequest(BaseModel):
    """A match template plus paging.

    Every field set on `country` must match; `name` matches as a
    case-insensitive substring, because a search box is what types into it.
    """

    model_config = ConfigDict(extra="forbid")

    country: Country = Field(default_factory=Country)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CountryQueryResponse(BaseModel):
    countries: list[Country]
    total: int


class CityQueryRequest(BaseModel):
    """As `CountryQueryRequest`. `country_id` matches exactly -- it is an id,
    not something anyone types."""

    model_config = ConfigDict(extra="forbid")

    city: City = Field(default_factory=City)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CityQueryResponse(BaseModel):
    cities: list[City]
    total: int


class HealthResponse(BaseModel):
    status: str
    service: str
