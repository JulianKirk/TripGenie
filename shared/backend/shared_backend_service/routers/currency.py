"""Currency endpoints -- the public read surface.

Separate from `location.py` because a currency is not a place. Each route wraps
the matching endpoint on the database service; the client turns anything
unusable into the documented 502/503, so these bodies stay one line. POST exists
on the database service but is not exposed, same rule as countries and cities.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, HTTPException, Query, status

from shared_backend_service import ids
from shared_backend_service.client import parse
from shared_backend_service.dependencies import DbDep  # noqa: TC001  (runtime)
from shared_backend_service.schemas import (
    Country,
    Currency,
    CurrencyQueryRequest,
    CurrencyQueryResponse,
)

router = APIRouter(prefix="/currency", tags=["currency"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Name = Annotated[str, Query(min_length=1)]

NO_CURRENCY = "country has no currency"


@router.get("/country", response_model=Currency, response_model_exclude_none=True)
async def currency_for_country(db: DbDep, name: Name) -> Currency:
    """The currency a country spends, by the country's name.

    The shortcut for the two calls every caller would otherwise make itself --
    the country, then the currency for its id. One country has at most one
    currency, so there is one answer or none.

    The name is matched *exactly*, unlike the substring matching in
    QUERY /location/country: the id is computed from the name rather than
    searched for (see ids.py), so `?name=austral` is a clean 404 instead of
    whatever Australia-shaped row a search happened to turn up first.

    Looking a currency up by its own ISO 4217 code is QUERY /currency, not this
    -- a code is not unique, so "who spends EUR" has a list for an answer.

    Declared before `/{id:uuid}` for readability only; the `:uuid` convertor
    already keeps that route from swallowing this path.
    """
    country = parse(Country, await db.get("country", ids.country_id(name)))
    found = parse(
        CurrencyQueryResponse,
        await db.query_currency({"currency": {"country_id": str(country.id)}}),
    )
    if not found.currencies:
        # The country exists and simply has no currency recorded -- a different
        # answer to "no such country", and worth saying so.
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_CURRENCY)
    return found.currencies[0]


@router.get("/{id:uuid}", response_model=Currency, response_model_exclude_none=True)
async def get_currency(id: UUID, db: DbDep) -> Currency:
    return parse(Currency, await db.get_currency(id))


@router.get("", response_model=CurrencyQueryResponse, response_model_exclude_none=True)
async def list_currency(
    db: DbDep, limit: Limit = 20, offset: Offset = 0
) -> CurrencyQueryResponse:
    """The no-filter QUERY, as a plain GET. There is one currency per country,
    so the whole list fits in a page and a caller can hold it beside the country
    list it already keeps."""
    return parse(
        CurrencyQueryResponse,
        await db.query_currency({"limit": limit, "offset": offset}),
    )


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=CurrencyQueryResponse,
    response_model_exclude_none=True,
)
async def query_currency(
    query: CurrencyQueryRequest, db: DbDep
) -> CurrencyQueryResponse:
    # exclude_none because the database service forbids unknown fields but
    # would accept an explicit null and filter on it. Send only what the caller
    # actually set.
    body = await db.query_currency(query.model_dump(mode="json", exclude_none=True))
    return parse(CurrencyQueryResponse, body)
