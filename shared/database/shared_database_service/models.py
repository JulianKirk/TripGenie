"""Shared reference microservice ORM models.

See ../../docs/object-model.md for the design (entities + ERD).

These two tables used to live in the accommodation service's `models.py`, under
a heading that admitted the arrangement was temporary: they were shared
entities parked in their only consumer. They are here now, and every service
references them by id.

The tables also own the translation to and from the wire messages in
`schemas.py` -- `to_message` and `get_or_create` below. A row knows how to
describe itself; the routers just call these.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from shared_database_service import ids, schemas

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class Base(DeclarativeBase):
    """Declarative base every ORM model in this service inherits from."""


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ships with FK enforcement off, so RESTRICT below is a no-op
    without this. Applies to every engine, including the test fixtures'."""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


class Country(Base):
    """Reference list of countries -- just a name, nothing else."""

    __tablename__ = "countries"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)

    cities: Mapped[list[City]] = relationship(back_populates="country")

    @classmethod
    def get_or_create(cls, session: Session, name: str) -> Country:
        """Look up by the id the name hashes to, and insert if it is not there.

        The id comes from `ids.country_id` rather than a fresh uuid4: services
        that cannot call this one derive the same id from the same name, and a
        row that appeared any other way would not match theirs.
        """
        name = ids.normalise(name)
        country = session.get(cls, ids.country_id(name))
        if country is None:
            country = cls(id=ids.country_id(name), name=name)
            session.add(country)
            session.flush()  # so a City created in the same request sees it
        return country

    def to_message(self) -> schemas.Country:
        return schemas.Country(id=self.id, name=self.name)


class City(Base):
    """Reference list of cities, scoped to a country (Sydney, Canada is a
    different row to Sydney, Australia)."""

    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("name", "country_id", name="uq_city_country"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    country_id: Mapped[UUID] = mapped_column(
        ForeignKey("countries.id", ondelete="RESTRICT")
    )

    country: Mapped[Country] = relationship(back_populates="cities")

    @classmethod
    def get_or_create(cls, session: Session, name: str, country: Country) -> City:
        """Takes the `Country` row, not its id: the id rule is scoped by country
        *name*, so creating a city means having the country in hand anyway --
        and taking the row is what makes an unknown country impossible here
        rather than a foreign-key error two lines later.
        """
        name = ids.normalise(name)
        city = session.get(cls, ids.city_id(country.name, name))
        if city is None:
            city = cls(
                id=ids.city_id(country.name, name), name=name, country_id=country.id
            )
            session.add(city)
            session.flush()
        return city

    def to_message(self) -> schemas.City:
        return schemas.City(id=self.id, name=self.name, country_id=self.country_id)
