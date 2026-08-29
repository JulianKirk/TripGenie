"""Repository classes for the accommodation microservice.

Each repository wraps a SQLAlchemy Session and exposes plain CRUD/query
methods -- callers work with these instead of touching Session/SQL directly.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    Accommodation,
    AccommodationBooking,
    AccommodationRating,
    RoomDetails,
)


class AccommodationRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, accommodation: Accommodation) -> Accommodation:
        self.session.add(accommodation)
        self.session.commit()
        return accommodation

    def get(self, id: UUID) -> Accommodation | None:
        return self.session.get(Accommodation, id)

    def list(self) -> list[Accommodation]:
        return list(self.session.scalars(select(Accommodation)))

    def delete(self, id: UUID) -> None:
        accommodation = self.get(id)
        if accommodation is not None:
            self.session.delete(accommodation)
            self.session.commit()

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
        self.session.commit()
        return booking

    def get(self, id: UUID) -> AccommodationBooking | None:
        return self.session.get(AccommodationBooking, id)

    def list(self) -> list[AccommodationBooking]:
        return list(self.session.scalars(select(AccommodationBooking)))

    def delete(self, id: UUID) -> None:
        booking = self.get(id)
        if booking is not None:
            self.session.delete(booking)
            self.session.commit()

class AccommodationRatingRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, rating: AccommodationRating) -> AccommodationRating:
        self.session.add(rating)
        self.session.commit()
        return rating

    def get(self, id: UUID) -> AccommodationRating | None:
        return self.session.get(AccommodationRating, id)

    def list(self) -> list[AccommodationRating]:
        return list(self.session.scalars(select(AccommodationRating)))

    def delete(self, id: UUID) -> None:
        rating = self.session.get(AccommodationRating, id)
        if rating is not None:
            self.session.delete(rating)
            self.session.commit()


