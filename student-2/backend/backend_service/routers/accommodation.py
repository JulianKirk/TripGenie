"""Accommodation endpoints -- the public read surface.

Each one wraps the matching endpoint on the database service; the client turns
anything unusable into the documented 502/503, so these bodies stay short.
The full CRUD set is here -- create, read, update, delete -- because the page in
front of this service is where an accommodation is authored as well as browsed.

The database service stores a place as the shared reference service's country
and city *ids*; this service publishes *names*. The two `_named` / `_by_id`
helpers below are where that translation happens, and the only reason these
routes are more than one line each.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from backend_service.client import parse
from backend_service.dependencies import (  # noqa: TC001  (runtime)
    DbDep,
    LocationDep,
)
from backend_service.schemas import (
    Accommodation,
    AccommodationCreateRequest,
    AccommodationQueryRequest,
    AccommodationQueryResponse,
    AccommodationUpdateRequest,
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


async def _place_by_id(place: dict[str, Any] | None, location: LocationClient) -> bool:
    """Swap a named place for the stored ids, in place. `False` when no such
    place exists -- what the caller does about that differs between a search and
    a write, so this only reports it.

    A place with no country is left alone: on a search that is "no place
    filter", and on an edit it is a street change that names no new city.
    """
    if place is None or "country" not in place:
        return True
    ids = await location.ids(place.pop("country"), place.pop("city", None))
    if ids is None:
        return False
    country_id, city_id = ids
    place["country_id"] = str(country_id)
    if city_id is not None:
        place["city_id"] = str(city_id)
    return True


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
    return body if await _place_by_id(place, location) else None


async def _stored(payload: Accommodation, location: LocationClient) -> dict[str, Any]:
    """A write body, as the database service wants it: place named on the way
    in, identified on the way down.

    Unlike a search, a place nobody has heard of is a 400 and not an empty
    answer -- you cannot store an accommodation in Narnia.
    """
    body = payload.model_dump(mode="json", exclude_none=True)
    if not await _place_by_id(body.get("location_details"), location):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown country or city")
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


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Accommodation,
    response_model_exclude_none=True,
)
async def create_accommodation(
    payload: AccommodationCreateRequest, db: DbDep, location: LocationDep
) -> Accommodation:
    """Store a new accommodation. Answers with the id and name the database
    service minted -- enough to link to it -- and nothing else, since the rest
    is what the caller just sent."""
    return parse(Accommodation, await db.create(await _stored(payload, location)))


@router.put(
    "/{id:uuid}", response_model=Accommodation, response_model_exclude_none=True
)
async def update_accommodation(
    id: UUID, payload: AccommodationUpdateRequest, db: DbDep, location: LocationDep
) -> Accommodation:
    """Edit an accommodation. A merge: fields left out keep their stored value.

    Answers with the whole row as it now stands, place named again, so a caller
    that has just saved does not need a second GET to redraw.
    """
    body = await db.update(id, await _stored(payload, location))
    return parse(Accommodation, await _named(body, location))


@router.delete("/{id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_accommodation(id: UUID, db: DbDep) -> Response:
    """Remove an accommodation. 404 if it was never there -- the database
    service decides that, and its answer relays through unchanged.

    No location client: nothing is named on the way out of a 204.
    """
    await db.delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
