"""Accommodation user rating endpoints."""

from __future__ import annotations

from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, status

from database_service.dependencies import (
    LimitDep,
    OffsetDep,
    SessionDep,
    get_or_404,
)
from database_service.models import AccommodationUserRating
from database_service.repository import (
    AccommodationRepository,
    AccommodationUserRatingRepository,
)
from database_service.schemas import (
    RatingCreate,
    RatingCreated,
    RatingList,
    RatingOut,
)

router = APIRouter(prefix="/accommodation/rating", tags=["rating"])


@router.get("", response_model=RatingList)
def list_ratings(
    session: SessionDep, limit: LimitDep = 20, offset: OffsetDep = 0
) -> RatingList:
    rows, total = AccommodationUserRatingRepository(session).list(limit, offset)
    return RatingList(ratings=rows, total=total)


@router.get("/{id:uuid}", response_model=RatingOut)
def get_rating(id: UUID, session: SessionDep) -> AccommodationUserRating:
    return get_or_404(AccommodationUserRatingRepository(session), id, "rating")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RatingCreated)
def create_rating(
    payload: RatingCreate, session: SessionDep
) -> AccommodationUserRating:
    get_or_404(
        AccommodationRepository(session), payload.accommodation_id, "accommodation"
    )
    # ponytail: Accommodation.rating is not recomputed here. The API doc treats
    # it as a field the caller sets, not a derived average. Add the rollup when
    # something actually asks for an aggregate.
    return AccommodationUserRatingRepository(session).add(
        AccommodationUserRating(**payload.model_dump())
    )


@router.delete("/{id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rating(id: UUID, session: SessionDep) -> None:
    ratings = AccommodationUserRatingRepository(session)
    get_or_404(ratings, id, "rating")
    ratings.delete(id)
