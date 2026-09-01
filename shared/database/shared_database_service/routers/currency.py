"""Currency endpoints.

Separate from `location.py` because a currency is not a place -- it is the other
thing a country tells you. One router per resource, same as everywhere else; the
translation to and from messages lives on the model.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, HTTPException, Response, status

from shared_database_service.dependencies import SessionDep, get_or_404
from shared_database_service.repository import CountryRepository, CurrencyRepository
from shared_database_service.schemas import Currency as CurrencyMessage
from shared_database_service.schemas import (
    CurrencyCreateRequest,
    CurrencyQueryRequest,
    CurrencyQueryResponse,
)

router = APIRouter(prefix="/internal/currency", tags=["currency"])

ALREADY_SPENT = "country already has a currency"


@router.get(
    "/{id:uuid}", response_model=CurrencyMessage, response_model_exclude_none=True
)
def get_currency(id: UUID, session: SessionDep) -> CurrencyMessage:
    return get_or_404(CurrencyRepository(session), id, "currency").to_message()


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=CurrencyQueryResponse,
    response_model_exclude_none=True,
)
def query_currency(
    query: CurrencyQueryRequest, session: SessionDep
) -> CurrencyQueryResponse:
    rows, total = CurrencyRepository(session).search(query)
    return CurrencyQueryResponse(
        currencies=[row.to_message() for row in rows], total=total
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CurrencyMessage,
    response_model_exclude_none=True,
)
def create_currency(
    payload: CurrencyCreateRequest, session: SessionDep, response: Response
) -> CurrencyMessage:
    """Create is get-or-create, as it is for a country or a city: `201` when
    this call inserted the row, `200` when it was already there. An existing row
    comes back untouched -- code, symbol and rate included -- this is not an
    update. Refreshing a stale rate needs an endpoint that does not exist yet.

    Giving a country a *second* currency is a `409`. The one-to-one is a UNIQUE
    constraint underneath, so without this it would surface as a 500 out of
    SQLite rather than an answer.
    """
    currencies = CurrencyRepository(session)
    country = get_or_404(CountryRepository(session), payload.country_id, "country")
    existing = currencies.for_country(country.id)
    if existing is not None and existing.name != payload.name.strip().lower():
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_SPENT)
    currency, created = currencies.add(
        payload.name, payload.code, payload.symbol, payload.conversion_rate, country
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return currency.to_message()
