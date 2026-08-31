"""Repository classes for the accommodation microservice.

Each repository wraps a SQLAlchemy Session and exposes plain CRUD/query
methods -- callers work with these instead of touching Session/SQL directly.
"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from database_service.models import (
    Accommodation,
    City,
    Country,
    LocationDetails,
    RoomDetails,
)
from database_service.schemas import Location, Room

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.orm import Session

    from database_service.schemas import Accommodation as AccommodationMessage
    from database_service.schemas import AccommodationQueryRequest


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


def _join_for(stmt: Select, query: AccommodationQueryRequest) -> Select:
    """Join only the tables this query actually touches -- an unconditional
    join to RoomDetails would silently drop accommodations that have none."""
    location = query.accommodation.location_details
    room = query.accommodation.room_details
    if location is not None:
        stmt = stmt.join(LocationDetails)
        if location.country is not None:
            stmt = stmt.join(Country, LocationDetails.country_id == Country.id)
        if location.city is not None:
            stmt = stmt.join(City, LocationDetails.city_id == City.id)
    if room is not None or (query.room_count_min, query.bed_count_min) != (None, None):
        stmt = stmt.join(RoomDetails)
    return stmt


def _equalities(match: AccommodationMessage) -> list[tuple[Any, Any]]:
    """(column, wanted) for the match template. A None means "not filtering"."""
    location = match.location_details or Location()
    room = match.room_details or Room()
    return [
        (Accommodation.name, match.name),
        (Accommodation.type, match.type),
        (Accommodation.description, match.description),
        (Accommodation.price_per_night, match.price_per_night),
        (Accommodation.availability_status, match.availability_status),
        (Accommodation.rating, match.rating),
        (Country.name, location.country),
        (City.name, location.city),
        (LocationDetails.street, location.street),
        (LocationDetails.street_number, location.street_number),
        (RoomDetails.room_count, room.room_count),
        (RoomDetails.bed_count, room.bed_count),
        (RoomDetails.description, room.description),
    ]


def _bounds(query: AccommodationQueryRequest) -> list[tuple[Any, Any, Any]]:
    """(column, comparison, bound) for the range filters. Add a new range by
    adding a field to AccommodationQueryRequest and a line here."""
    return [
        (Accommodation.price_per_night, operator.ge, query.price_min),
        (Accommodation.price_per_night, operator.le, query.price_max),
        (Accommodation.rating, operator.ge, query.rating_min),
        (Accommodation.rating, operator.le, query.rating_max),
        (RoomDetails.room_count, operator.ge, query.room_count_min),
        (RoomDetails.bed_count, operator.ge, query.bed_count_min),
    ]


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
        self, query: AccommodationQueryRequest
    ) -> tuple[list[Accommodation], int]:
        """Backs QUERY /accommodation.

        `query.accommodation` is a match template -- any field set on it has to
        match exactly. The `*_min`/`*_max` fields carry the comparisons a
        template cannot express. Everything is optional and everything stacks.
        """
        stmt = _join_for(select(Accommodation), query)
        for column, value in _equalities(query.accommodation):
            if value is not None:
                stmt = stmt.where(column == value)
        for column, compare, bound in _bounds(query):
            if bound is not None:
                stmt = stmt.where(compare(column, bound))
        return _paginate(self.session, stmt, query.limit, query.offset)
