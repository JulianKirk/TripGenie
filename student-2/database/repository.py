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
    AccommodationUserRating,
    City,
    Country,
    LocationDetails,
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

    def list_by_city(self, city: str, country: str) -> list[Accommodation]:
        """Everything bookable in one city -- what the itinerary service asks for."""
        stmt = (
            select(Accommodation)
            .join(LocationDetails)
            .join(Country, LocationDetails.country_id == Country.id)
            .join(City, LocationDetails.city_id == City.id)
            .where(Country.name == country, City.name == city)
        )
        return list(self.session.scalars(stmt))

    def list_by_min_room_count(self, min_room_count: int) -> list[Accommodation]:
        stmt = (
            select(Accommodation)
            .join(RoomDetails)
            .where(RoomDetails.room_count >= min_room_count)
        )
        return list(self.session.scalars(stmt))


class CountryRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, country: Country) -> Country:
        self.session.add(country)
        _commit(self.session)
        return country

    def get(self, id: UUID) -> Country | None:
        return self.session.get(Country, id)

    def get_by_name(self, name: str) -> Country | None:
        return self.session.scalar(select(Country).where(Country.name == name))

    def list(self) -> list[Country]:
        return list(self.session.scalars(select(Country)))

    def delete(self, id: UUID) -> None:
        country = self.get(id)
        if country is not None:
            self.session.delete(country)
            _commit(self.session)


class CityRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, city: City) -> City:
        self.session.add(city)
        _commit(self.session)
        return city

    def get(self, id: UUID) -> City | None:
        return self.session.get(City, id)

    def get_by_name(self, name: str, country_id: UUID) -> City | None:
        stmt = select(City).where(City.name == name, City.country_id == country_id)
        return self.session.scalar(stmt)

    def list(self) -> list[City]:
        return list(self.session.scalars(select(City)))

    def delete(self, id: UUID) -> None:
        city = self.get(id)
        if city is not None:
            self.session.delete(city)
            _commit(self.session)


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


class AccommodationUserRatingRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, rating: AccommodationUserRating) -> AccommodationUserRating:
        self.session.add(rating)
        _commit(self.session)
        return rating

    def get(self, id: UUID) -> AccommodationUserRating | None:
        return self.session.get(AccommodationUserRating, id)

    def list(self) -> list[AccommodationUserRating]:
        return list(self.session.scalars(select(AccommodationUserRating)))

    def delete(self, id: UUID) -> None:
        rating = self.session.get(AccommodationUserRating, id)
        if rating is not None:
            self.session.delete(rating)
            _commit(self.session)
