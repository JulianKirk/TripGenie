"""Repository classes for the accommodation microservice.

Each repository wraps a SQLAlchemy Session and exposes plain CRUD/query
methods -- callers work with these instead of touching Session/SQL directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from database.models import (
    Accommodation,
    AccommodationBooking,
    AccommodationRating,
    RoomDetails,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session


def _commit(session: Session) -> None:
    """Commit, rolling back on failure so a shared Session stays usable."""
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


class AccommodationRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, accommodation: Accommodation) -> Accommodation:
        self.session.add(accommodation)
        _commit(self.session)
        return accommodation

    def get(self, id: UUID) -> Accommodation | None:
        return self.session.get(Accommodation, id)

    def list(self) -> list[Accommodation]:
        return list(self.session.scalars(select(Accommodation)))

    def delete(self, id: UUID) -> None:
        accommodation = self.get(id)
        if accommodation is not None:
            self.session.delete(accommodation)
            _commit(self.session)

    def list_by_min_room_count(self, min_room_count: int) -> list[Accommodation]:
        stmt = (
            select(Accommodation)
            .join(RoomDetails)
            .where(RoomDetails.room_count >= min_room_count)
        )
        return list(self.session.scalars(stmt))


class AccommodationBookingRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, booking: AccommodationBooking) -> AccommodationBooking:
        self.session.add(booking)
        _commit(self.session)
        return booking

    def get(self, id: UUID) -> AccommodationBooking | None:
        return self.session.get(AccommodationBooking, id)

    def list(self) -> list[AccommodationBooking]:
        return list(self.session.scalars(select(AccommodationBooking)))

    def delete(self, id: UUID) -> None:
        booking = self.get(id)
        if booking is not None:
            self.session.delete(booking)
            _commit(self.session)


class AccommodationRatingRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, rating: AccommodationRating) -> AccommodationRating:
        self.session.add(rating)
        _commit(self.session)
        return rating

    def get(self, id: UUID) -> AccommodationRating | None:
        return self.session.get(AccommodationRating, id)

    def list(self) -> list[AccommodationRating]:
        return list(self.session.scalars(select(AccommodationRating)))

    def delete(self, id: UUID) -> None:
        rating = self.session.get(AccommodationRating, id)
        if rating is not None:
            self.session.delete(rating)
            _commit(self.session)
