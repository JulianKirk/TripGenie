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
    # uselist=False is the one-to-one: a country has at most one currency.
    currency: Mapped[Currency | None] = relationship(
        back_populates="country", uselist=False
    )

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


class Currency(Base):
    """The money a country spends, one country to one currency.

    That is a deliberate simplification of the real world -- France and Italy
    both spend euros, and here those are two rows with the same name and symbol
    under different countries. It is what makes "what does this cost here"
    answerable from a country id alone, which is the question every service
    that shows a price actually asks.

    ponytail: `conversion_rate` is a stored number, not a feed. The seeded values are
    indicative and go stale the day they are written -- fine for showing "about
    ¥9,800", wrong for anything anyone is charged. There is also no way to
    update one: `POST` is get-or-create, so refreshing a rate is the first
    endpoint to add when the numbers have to be current.
    """

    __tablename__ = "currencies"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    # ISO 4217, stored upper case: AUD, JPY, EUR. Not unique -- under the
    # one-to-one rule France's euro and Italy's euro are two rows, and both are
    # EUR. A code identifies a currency, not a row.
    code: Mapped[str]
    symbol: Mapped[str]
    # How many units of this currency 1 AUD buys. TripGenie is an Australian
    # service, so AUD is the base and its own row is exactly 1.0 -- the local
    # currency needs no conversion, and having it in the table rather than as a
    # special case means "convert" is one multiplication with no branch.
    conversion_rate: Mapped[float]
    # unique, not just a foreign key -- this is where the one-to-one is
    # enforced rather than merely intended.
    country_id: Mapped[UUID] = mapped_column(
        ForeignKey("countries.id", ondelete="RESTRICT"), unique=True
    )

    country: Mapped[Country] = relationship(back_populates="currency")

    @classmethod
    def get_or_create(
        cls,
        session: Session,
        name: str,
        code: str,
        symbol: str,
        conversion_rate: float,
        country: Country,
    ) -> Currency:
        """Same look-up-or-insert as the other two, and takes the `Country` row
        for the same reason `City.get_or_create` does.

        An existing row is returned untouched -- code, symbol and rate
        included: this is get-or-create, not an update. The router is what
        refuses to give a country a second currency -- see
        routers/currency.py.
        """
        name = ids.normalise(name)
        currency = session.get(cls, ids.currency_id(country.name, name))
        if currency is None:
            currency = cls(
                id=ids.currency_id(country.name, name),
                name=name,
                code=ids.normalise_code(code),
                symbol=symbol,
                conversion_rate=conversion_rate,
                country_id=country.id,
            )
            session.add(currency)
            session.flush()
        return currency

    def to_message(self) -> schemas.Currency:
        return schemas.Currency(
            id=self.id,
            name=self.name,
            code=self.code,
            symbol=self.symbol,
            conversion_rate=self.conversion_rate,
            country_id=self.country_id,
        )
