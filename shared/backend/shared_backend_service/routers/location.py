"""Country and city endpoints -- the public read surface.

Each one wraps the matching endpoint on the database service; the client turns
anything unusable into the documented 502/503, so these bodies stay one line.
POST exists on the database service but is not exposed: the reference lists are
seeded, and this service's users read places, they do not invent them.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, Query

from shared_backend_service.client import parse
from shared_backend_service.dependencies import DbDep  # noqa: TC001  (runtime)
from shared_backend_service.schemas import (
    City,
    CityQueryRequest,
    CityQueryResponse,
    Country,
    CountryQueryRequest,
    CountryQueryResponse,
)

# The `:uuid` convertor keeps the {id} routes matching only well-formed UUIDs,
# so a future sub-resource path cannot be swallowed by one.
router = APIRouter(prefix="/location", tags=["location"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/country/{id:uuid}", response_model=Country, response_model_exclude_none=True
)
async def get_country(id: UUID, db: DbDep) -> Country:
    return parse(Country, await db.get("country", id))


@router.get(
    "/country", response_model=CountryQueryResponse, response_model_exclude_none=True
)
async def list_country(
    db: DbDep, limit: Limit = 20, offset: Offset = 0
) -> CountryQueryResponse:
    """The no-filter QUERY, as a plain GET so a browser or an hx-get can reach
    it without a request body. This is also the endpoint the other students'
    backends page through to build a name-to-id map."""
    return parse(
        CountryQueryResponse,
        await db.query("country", {"limit": limit, "offset": offset}),
    )


@router.api_route(
    "/country",
    methods=["QUERY"],
    response_model=CountryQueryResponse,
    response_model_exclude_none=True,
)
async def query_country(query: CountryQueryRequest, db: DbDep) -> CountryQueryResponse:
    # exclude_none because the database service forbids unknown fields but
    # would accept an explicit null and filter on it. Send only what the
    # caller actually set.
    body = await db.query("country", query.model_dump(mode="json", exclude_none=True))
    return parse(CountryQueryResponse, body)


@router.get("/city/{id:uuid}", response_model=City, response_model_exclude_none=True)
async def get_city(id: UUID, db: DbDep) -> City:
    return parse(City, await db.get("city", id))


@router.get("/city", response_model=CityQueryResponse, response_model_exclude_none=True)
async def list_city(
    db: DbDep, limit: Limit = 20, offset: Offset = 0
) -> CityQueryResponse:
    """As `list_country`."""
    return parse(
        CityQueryResponse, await db.query("city", {"limit": limit, "offset": offset})
    )


@router.api_route(
    "/city",
    methods=["QUERY"],
    response_model=CityQueryResponse,
    response_model_exclude_none=True,
)
async def query_city(query: CityQueryRequest, db: DbDep) -> CityQueryResponse:
    body = await db.query("city", query.model_dump(mode="json", exclude_none=True))
    return parse(CityQueryResponse, body)
