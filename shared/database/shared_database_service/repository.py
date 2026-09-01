"""Repository classes for the shared reference microservice.

Each repository wraps a SQLAlchemy Session and exposes plain CRUD/query
methods -- callers work with these instead of touching Session/SQL directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from shared_database_service import ids
from shared_database_service.models import City, Country

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.orm import Session

    from shared_database_service.schemas import CityQueryRequest, CountryQueryRequest


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


class CountryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, id: UUID) -> Country | None:
        return self.session.get(Country, id)

    def add(self, name: str) -> tuple[Country, bool]:
        """The row for `name`, and whether this call is what put it there --
        the router turns that flag into a 201 or a 200. Create is idempotent
        because the id is the name: posting the same country twice cannot make
        two rows."""
        created = self.get(ids.country_id(name)) is None
        country = Country.get_or_create(self.session, name)
        _commit(self.session)
        return country, created

    def search(self, query: CountryQueryRequest) -> tuple[list[Country], int]:
        """Backs QUERY /internal/location/country. `id` matches exactly, `name`
        as a case-insensitive substring -- an exact match on a name is no use
        to someone still typing."""
        match = query.country
        stmt = select(Country)
        if match.id is not None:
            stmt = stmt.where(Country.id == match.id)
        if match.name is not None:
            stmt = stmt.where(Country.name.ilike(f"%{ids.normalise(match.name)}%"))
        # A window without an ORDER BY is not a stable page -- SQLite may hand
        # back the same row twice across two pages.
        stmt = stmt.order_by(Country.name, Country.id)
        return _paginate(self.session, stmt, query.limit, query.offset)


class CityRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, id: UUID) -> City | None:
        return self.session.get(City, id)

    def add(self, name: str, country: Country) -> tuple[City, bool]:
        """Same idempotence as `CountryRepository.add`. Takes the `Country` row
        because the id rule is scoped by country name -- see
        `City.get_or_create`."""
        created = self.get(ids.city_id(country.name, name)) is None
        city = City.get_or_create(self.session, name, country)
        _commit(self.session)
        return city, created

    def search(self, query: CityQueryRequest) -> tuple[list[City], int]:
        """Backs QUERY /internal/location/city. As countries, plus an exact
        match on `country_id` -- that one is an id, not something anyone
        types."""
        match = query.city
        stmt = select(City)
        if match.id is not None:
            stmt = stmt.where(City.id == match.id)
        if match.country_id is not None:
            stmt = stmt.where(City.country_id == match.country_id)
        if match.name is not None:
            stmt = stmt.where(City.name.ilike(f"%{ids.normalise(match.name)}%"))
        stmt = stmt.order_by(City.name, City.id)
        return _paginate(self.session, stmt, query.limit, query.offset)
