"""Country and city endpoints.

Every route returns a `schemas.Country` or `schemas.City` with `exclude_none`,
so what a response contains is decided by which fields the handler fills in
rather than by a per-endpoint response class. The ORM to message translation
lives on the models (`to_message` / `get_or_create`).
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, Response, status

from shared_database_service.dependencies import SessionDep, get_or_404
from shared_database_service.repository import CityRepository, CountryRepository
from shared_database_service.schemas import City as CityMessage
from shared_database_service.schemas import (
    CityCreateRequest,
    CityQueryRequest,
    CityQueryResponse,
    CountryCreateRequest,
    CountryQueryRequest,
    CountryQueryResponse,
)
from shared_database_service.schemas import Country as CountryMessage

# The `:uuid` convertor keeps the {id} routes matching only well-formed UUIDs,
# so a future sub-resource path cannot be swallowed by one.
router = APIRouter(prefix="/internal/location", tags=["location"])


@router.get(
    "/country/{id:uuid}",
    response_model=CountryMessage,
    response_model_exclude_none=True,
)
def get_country(id: UUID, session: SessionDep) -> CountryMessage:
    return get_or_404(CountryRepository(session), id, "country").to_message()


@router.api_route(
    "/country",
    methods=["QUERY"],
    response_model=CountryQueryResponse,
    response_model_exclude_none=True,
)
def query_country(
    query: CountryQueryRequest, session: SessionDep
) -> CountryQueryResponse:
    rows, total = CountryRepository(session).search(query)
    return CountryQueryResponse(
        countries=[row.to_message() for row in rows], total=total
    )


@router.post(
    "/country",
    status_code=status.HTTP_201_CREATED,
    response_model=CountryMessage,
    response_model_exclude_none=True,
)
def create_country(
    payload: CountryCreateRequest, session: SessionDep, response: Response
) -> CountryMessage:
    """Create is get-or-create: an id is the name, so posting the same country
    twice cannot make two rows. `201` when this call inserted it, `200` when it
    was already there -- the caller wanted the id either way."""
    country, created = CountryRepository(session).add(payload.name)
    if not created:
        response.status_code = status.HTTP_200_OK
    return country.to_message()


@router.get(
    "/city/{id:uuid}", response_model=CityMessage, response_model_exclude_none=True
)
def get_city(id: UUID, session: SessionDep) -> CityMessage:
    return get_or_404(CityRepository(session), id, "city").to_message()


@router.api_route(
    "/city",
    methods=["QUERY"],
    response_model=CityQueryResponse,
    response_model_exclude_none=True,
)
def query_city(query: CityQueryRequest, session: SessionDep) -> CityQueryResponse:
    rows, total = CityRepository(session).search(query)
    return CityQueryResponse(cities=[row.to_message() for row in rows], total=total)


@router.post(
    "/city",
    status_code=status.HTTP_201_CREATED,
    response_model=CityMessage,
    response_model_exclude_none=True,
)
def create_city(
    payload: CityCreateRequest, session: SessionDep, response: Response
) -> CityMessage:
    """As `create_country`. The country has to exist first -- a city's id is
    derived from its country's *name*, so an unknown `country_id` is a 404
    here rather than a foreign-key error further down."""
    country = get_or_404(CountryRepository(session), payload.country_id, "country")
    city, created = CityRepository(session).add(payload.name, country)
    if not created:
        response.status_code = status.HTTP_200_OK
    return city.to_message()
