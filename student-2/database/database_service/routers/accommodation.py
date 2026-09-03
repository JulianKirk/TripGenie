"""Accommodation endpoints.

Every route returns a `schemas.Accommodation` with `exclude_none`, so what a
response contains is decided by which fields the handler fills in rather than
by a per-endpoint response class. The ORM ↔ message translation lives on the
models (`to_message` / `from_message` / `update_from`).
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, Response, status

from database_service.dependencies import SessionDep, get_or_404
from database_service.models import Accommodation
from database_service.repository import AccommodationRepository
from database_service.schemas import Accommodation as AccommodationMessage
from database_service.schemas import (
    AccommodationCreateRequest,
    AccommodationQueryRequest,
    AccommodationQueryResponse,
)

# The `:uuid` convertor keeps /internal/accommodation/{id} matching only well-formed
# UUIDs, so a future sub-resource path cannot be swallowed by it.
router = APIRouter(prefix="/internal/accommodation", tags=["accommodation"])


@router.get(
    "/{id:uuid}", response_model=AccommodationMessage, response_model_exclude_none=True
)
def get_accommodation(id: UUID, session: SessionDep) -> AccommodationMessage:
    row = get_or_404(AccommodationRepository(session), id, "accommodation")
    return row.to_message()


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=AccommodationQueryResponse,
    response_model_exclude_none=True,
)
def query_accommodation(
    query: AccommodationQueryRequest, session: SessionDep
) -> AccommodationQueryResponse:
    rows, total = AccommodationRepository(session).search(query)
    return AccommodationQueryResponse(
        accommodations=[row.to_message().summary() for row in rows], total=total
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AccommodationMessage,
    response_model_exclude_none=True,
)
def create_accommodation(
    payload: AccommodationCreateRequest, session: SessionDep
) -> AccommodationMessage:
    accommodation = AccommodationRepository(session).add(
        Accommodation.from_message(payload)
    )
    # Only the fields the caller needs to find the row again -- the rest are
    # None and `exclude_none` drops them.
    return AccommodationMessage(id=accommodation.id, name=accommodation.name)


@router.put(
    "/{id:uuid}", response_model=AccommodationMessage, response_model_exclude_none=True
)
def update_accommodation(
    id: UUID, payload: AccommodationMessage, session: SessionDep
) -> AccommodationMessage:
    accommodations = AccommodationRepository(session)
    accommodation = get_or_404(accommodations, id, "accommodation")
    accommodation.update_from(payload)
    # add() on an already-persistent instance is a no-op plus the commit.
    return accommodations.add(accommodation).to_message()


@router.delete("/{id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_accommodation(id: UUID, session: SessionDep) -> Response:
    """Gone, along with its location and room rows -- the relationships cascade.

    `get_or_404` first, so deleting something that is not there is the same 404
    as reading it, rather than a silent success. The repository's own delete is
    a no-op on a missing id, which is the wrong answer for a caller that wants
    to know.
    """
    accommodations = AccommodationRepository(session)
    get_or_404(accommodations, id, "accommodation")
    accommodations.delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
