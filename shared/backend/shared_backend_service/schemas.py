"""The wire format this service publishes -- the shared reference contract.

These mirror `shared_database_service/schemas.py`, deliberately duplicated
rather than imported. This service is the public face: every other student's
backend codes against what *it* documents and serves at /docs, and they cannot
reach the internal service that would otherwise own the shape. Importing it
would also put the database package inside this image, so the two would stop
being independently deployable.

The cost is a second representation. When the database service adds a field,
`extra="forbid"` makes parsing its response fail and the route returns the
documented 502 -- a loud failure, not a silent one, and the end-to-end tests in
tests/e2e run the real database app, so drift breaks CI immediately. Add the
field here to fix it.

One message, nullable fields -- the protobuf convention, same as the database
service. `Country` is both the search template and every country response body;
which fields are populated is what differs, and routes serialise with
`response_model_exclude_none=True` so an unset field is absent rather than null.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Country(BaseModel):
    """A country. Its id is stable for a given name -- see the id rule in
    ../../docs/object-model.md."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    name: str | None = None


class City(BaseModel):
    """A city, scoped to the country it sits in."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    name: str | None = None
    country_id: UUID | None = None


class Currency(BaseModel):
    """The money a country spends. One country, one currency -- see
    ../../docs/object-model.md for why that simplification is deliberate."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    name: str | None = None
    # ISO 4217, upper case: AUD, JPY, EUR. Not unique -- France's euro and
    # Italy's euro are two rows and both are EUR.
    code: str | None = Field(default=None, min_length=3, max_length=3)
    symbol: str | None = None
    # Units of this currency per 1 AUD. AUD itself is 1.0.
    conversion_rate: float | None = Field(default=None, gt=0)
    country_id: UUID | None = None


class CountryQueryRequest(BaseModel):
    """A match template plus paging.

    Forwarded to the database service as-is; its QUERY documents the template
    in full. Validated here so a malformed search is a 400 without a round
    trip, and so /docs describes the search this service accepts.
    """

    model_config = ConfigDict(extra="forbid")

    country: Country = Field(default_factory=Country)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CountryQueryResponse(BaseModel):
    countries: list[Country]
    total: int


class CityQueryRequest(BaseModel):
    """As `CountryQueryRequest`."""

    model_config = ConfigDict(extra="forbid")

    city: City = Field(default_factory=City)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CityQueryResponse(BaseModel):
    cities: list[City]
    total: int


class CurrencyQueryRequest(BaseModel):
    """As `CountryQueryRequest`."""

    model_config = ConfigDict(extra="forbid")

    currency: Currency = Field(default_factory=Currency)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CurrencyQueryResponse(BaseModel):
    currencies: list[Currency]
    total: int


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
