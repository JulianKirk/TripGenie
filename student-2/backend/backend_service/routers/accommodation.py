"""Accommodation endpoints -- the public read surface.

Each one wraps the matching endpoint on the database service; the client turns
anything unusable into the documented 502/503, so these bodies stay one line.
POST and PUT exist on the database service but are not exposed: this service's
users view and filter accommodations, they do not author them.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, Query

from backend_service.client import parse
from backend_service.dependencies import DbDep  # noqa: TC001  (runtime)
from backend_service.schemas import (
    Accommodation,
    AccommodationQueryRequest,
    AccommodationQueryResponse,
)

# The `:uuid` convertor keeps /accommodation/{id} matching only well-formed
# UUIDs, so a future sub-resource path cannot be swallowed by it.
router = APIRouter(prefix="/accommodation", tags=["accommodation"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/{id:uuid}", response_model=Accommodation, response_model_exclude_none=True
)
async def get_accommodation(id: UUID, db: DbDep) -> Accommodation:
    return parse(Accommodation, await db.get(id))


@router.get(
    "", response_model=AccommodationQueryResponse, response_model_exclude_none=True
)
async def list_accommodation(
    db: DbDep, limit: Limit = 20, offset: Offset = 0
) -> AccommodationQueryResponse:
    """The no-filter QUERY, as a plain GET so a browser or an hx-get can reach
    it without a request body."""
    return parse(
        AccommodationQueryResponse, await db.query({"limit": limit, "offset": offset})
    )


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=AccommodationQueryResponse,
    response_model_exclude_none=True,
)
async def query_accommodation(
    query: AccommodationQueryRequest, db: DbDep
) -> AccommodationQueryResponse:
    # exclude_none because the database service forbids unknown fields but
    # would accept an explicit null bound and filter on it. Send only what the
    # caller actually set.
    body = await db.query(query.model_dump(mode="json", exclude_none=True))
    return parse(AccommodationQueryResponse, body)
