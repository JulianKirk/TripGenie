"""Repository classes for the accommodation microservice.

Each repository wraps a SQLAlchemy Session and exposes plain CRUD/query
methods -- callers work with these instead of touching Session/SQL directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from database_service.models import (
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

    from sqlalchemy import Select
    from sqlalchemy.orm import Session


def _paginate(
    session: Session, stmt: Select, limit: int, offset: int
) -> tuple[list, int]:
    """Run `stmt` windowed, plus a COUNT over the same filters.

    The count has to be a second query -- a window function would need one row
    back to read the total from, and an empty page has none.
    """
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(session.scalars(stmt.limit(limit).offset(offset)))
    return rows, total


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

    def delete(self, id: UUID) -> None:
        accommodation = self.get(id)
        if accommodation is not None:
            self.session.delete(accommodation)
            _commit(self.session)

    def search(
        self,
        *,
        country: str | None = None,
        city: str | None = None,
        min_room_count: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Accommodation], int]:
        """Backs QUERY /accommodation. Every filter is optional and they stack,
        so "3+ rooms in Sydney, Australia" is one query rather than an
        intersection done in Python.

        `city` without `country` is rejected at the API edge, not here -- Sydney
        exists in more than one country.
        """
        stmt = select(Accommodation)
        if country is not None:
            stmt = stmt.join(LocationDetails).join(
                Country, LocationDetails.country_id == Country.id
            )
            stmt = stmt.where(Country.name == country)
            if city is not None:
                stmt = stmt.join(City, LocationDetails.city_id == City.id).where(
                    City.name == city
                )
        if min_room_count is not None:
            stmt = stmt.join(RoomDetails).where(
                RoomDetails.room_count >= min_room_count
            )
        return _paginate(self.session, stmt, limit, offset)


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

    def list(
        self, limit: int = 20, offset: int = 0
    ) -> tuple[list[AccommodationBooking], int]:
        return _paginate(self.session, select(AccommodationBooking), limit, offset)

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

    def list(
        self, limit: int = 20, offset: int = 0
    ) -> tuple[list[AccommodationUserRating], int]:
        return _paginate(self.session, select(AccommodationUserRating), limit, offset)

    def delete(self, id: UUID) -> None:
        rating = self.session.get(AccommodationUserRating, id)
        if rating is not None:
            self.session.delete(rating)
            _commit(self.session)
