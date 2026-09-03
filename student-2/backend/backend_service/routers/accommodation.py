"""Accommodation endpoints -- the public read surface.

Each one wraps the matching endpoint on the database service; the client turns
anything unusable into the documented 502/503, so these bodies stay short.
POST and PUT exist on the database service but are not exposed: this service's
users view and filter accommodations, they do not author them.

The database service stores a place as the shared reference service's country
and city *ids*; this service publishes *names*. The two `_named` / `_by_id`
helpers below are where that translation happens, and the only reason these
routes are more than one line each.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from backend_service.client import parse
from backend_service.dependencies import (  # noqa: TC001  (runtime)
    DbDep,
    LocationDep,
)
from backend_service.schemas import (
    Accommodation,
    AccommodationQueryRequest,
    AccommodationQueryResponse,
)

if TYPE_CHECKING:
    from backend_service.location_client import LocationClient

# The `:uuid` convertor keeps /accommodation/{id} matching only well-formed
# UUIDs, so a future sub-resource path cannot be swallowed by it.
router = APIRouter(prefix="/accommodation", tags=["accommodation"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

EMPTY = AccommodationQueryResponse(accommodations=[], total=0)
# (what the database service stores, what this service publishes)
PLACE_FIELDS = (("country_id", "country"), ("city_id", "city"))


def _places(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Every `location_details` object in a database service response.

    One helper for both response shapes: a single accommodation is the body,
    a query result is a list under `accommodations`.
    """
    rows = body.get("accommodations", [body])
    return [row["location_details"] for row in rows if "location_details" in row]


async def _named(body: dict[str, Any], location: LocationClient) -> dict[str, Any]:
    """Swap the stored ids for the published names, in place.

    One batch of ids for the whole response, so a page of 100 results costs one
    lookup rather than 200. An id the shared service does not know stays
    unnamed: `exclude_none` drops the field, so the row still returns and simply
    does not say where it is.
    """
    places = _places(body)
    ids = {
        UUID(place[stored])
        for place in places
        for stored, _ in PLACE_FIELDS
        if place.get(stored) is not None
    }
    names = await location.names(ids)
    for place in places:
        for stored, published in PLACE_FIELDS:
            stored_id = place.pop(stored, None)
            if stored_id is not None and UUID(stored_id) in names:
                place[published] = names[UUID(stored_id)]
    return body


async def _by_id(
    query: AccommodationQueryRequest, location: LocationClient
) -> dict[str, Any] | None:
    """The query body to forward, or `None` when it names a place that does not
    exist -- which is an empty result, not an error."""
    # exclude_none because the database service forbids unknown fields but
    # would accept an explicit null bound and filter on it. Send only what the
    # caller actually set.
    body = query.model_dump(mode="json", exclude_none=True)
    place = body.get("accommodation", {}).get("location_details")
    if place is None or "country" not in place:
        return body
    ids = await location.ids(place.pop("country"), place.pop("city", None))
    if ids is None:
        return None
    country_id, city_id = ids
    place["country_id"] = str(country_id)
    if city_id is not None:
        place["city_id"] = str(city_id)
    return body


@router.get(
    "/{id:uuid}", response_model=Accommodation, response_model_exclude_none=True
)
async def get_accommodation(
    id: UUID, db: DbDep, location: LocationDep
) -> Accommodation:
    return parse(Accommodation, await _named(await db.get(id), location))


@router.get(
    "", response_model=AccommodationQueryResponse, response_model_exclude_none=True
)
async def list_accommodation(
    db: DbDep, location: LocationDep, limit: Limit = 20, offset: Offset = 0
) -> AccommodationQueryResponse:
    """The no-filter QUERY, as a plain GET so a browser or an hx-get can reach
    it without a request body."""
    body = await db.query({"limit": limit, "offset": offset})
    return parse(AccommodationQueryResponse, await _named(body, location))


async def search(
    query: AccommodationQueryRequest, db: DbDep, location: LocationDep
) -> AccommodationQueryResponse:
    """Run a search. The QUERY route below is this and nothing else; the ask box
    in routers/ai.py calls it too, once the model has produced the filters.

    One search path rather than two, so the place-name translation, the empty
    result for an unknown country and the 502 on drift are the same however the
    filters were arrived at.
    """
    forwarded = await _by_id(query, location)
    if forwarded is None:
        # Nobody has accommodation in a country the shared service has never
        # heard of. That is an answer, not a failure.
        return EMPTY
    body = await db.query(forwarded)
    return parse(AccommodationQueryResponse, await _named(body, location))


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=AccommodationQueryResponse,
    response_model_exclude_none=True,
)
async def query_accommodation(
    query: AccommodationQueryRequest, db: DbDep, location: LocationDep
) -> AccommodationQueryResponse:
    return await search(query, db, location)
