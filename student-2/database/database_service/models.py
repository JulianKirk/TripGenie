"""Accommodation microservice ORM models.

See ../../docs/object-model.md for the design (entities + ERD).

The tables also own the translation to and from the wire messages in
`schemas.py` -- `to_message`, `from_message` and `update_from` below. A row
knows how to describe itself; the routers just call these.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, UniqueConstraint, event, select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.engine import Engine
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from database_service import schemas
from database_service.enums import AccommodationType, AvailabilityStatus, BedType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class Base(DeclarativeBase):
    """Declarative base every ORM model in this service inherits from."""


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ships with FK enforcement off, so RESTRICT below is a no-op
    without this. Applies to every engine, including the test fixtures'."""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


class BedTypesJSON(TypeDecorator):
    """Stores list[BedType] as a JSON array of enum values.

    ponytail: SQLAlchemy has no built-in "list of enum" column type, so this
    is the minimum custom code needed to keep BedType members on the Python
    side while storing plain JSON text in SQLite. Upgrade to a real
    room_bed_types join table only if bed type ever needs SQL-level filtering.
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [bed_type.value for bed_type in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [BedType(v) for v in value]


class Country(Base):
    """Reference list of countries -- just a name, nothing else."""

    __tablename__ = "countries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(unique=True)

    @classmethod
    def get_or_create(cls, session: Session, name: str) -> Country:
        """The backend sends place names, not ids -- it has no way to know
        ours -- so an unknown country is created rather than rejected."""
        country = session.scalar(select(cls).where(cls.name == name))
        if country is None:
            country = cls(name=name)
            session.add(country)
            session.flush()  # the id is assigned on INSERT, and callers need it
        return country


class City(Base):
    """Reference list of cities, scoped to a country (Sydney, Canada is a
    different row to Sydney, Australia)."""

    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("name", "country_id", name="uq_city_country"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    country_id: Mapped[UUID] = mapped_column(
        ForeignKey("countries.id", ondelete="RESTRICT")
    )

    country: Mapped[Country] = relationship()

    @classmethod
    def get_or_create(cls, session: Session, name: str, country_id: UUID) -> City:
        """Scoped to the country, so Sydney/Australia and Sydney/Canada are
        two rows rather than a collision."""
        city = session.scalar(
            select(cls).where(cls.name == name, cls.country_id == country_id)
        )
        if city is None:
            city = cls(name=name, country_id=country_id)
            session.add(city)
            session.flush()
        return city


class LocationDetails(Base):
    __tablename__ = "location_details"
    # Same reason as the RoomDetails index: the itinerary service asks "what
    # can I stay in at <place>", so country/city are the query keys.
    __table_args__ = (Index("ix_location_details_city", "country_id", "city_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    accommodation_id: Mapped[UUID] = mapped_column(
        ForeignKey("accommodations.id", ondelete="CASCADE"), unique=True
    )
    country_id: Mapped[UUID] = mapped_column(
        ForeignKey("countries.id", ondelete="RESTRICT")
    )
    city_id: Mapped[UUID] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    street: Mapped[str | None] = mapped_column(default=None)
    street_number: Mapped[int | None] = mapped_column(default=None)

    accommodation: Mapped[Accommodation] = relationship(
        back_populates="location_details"
    )
    country: Mapped[Country] = relationship()
    city: Mapped[City] = relationship()

    @classmethod
    def from_message(
        cls, session: Session, message: schemas.Location
    ) -> LocationDetails:
        country = Country.get_or_create(session, message.country)
        city = City.get_or_create(session, message.city, country.id)
        return cls(
            country_id=country.id,
            city_id=city.id,
            street=message.street,
            street_number=message.street_number,
        )

    def update_from(self, session: Session, message: schemas.Location) -> None:
        """Updated in place rather than replaced: reassigning the relationship
        cascades a delete + insert, which trips the UNIQUE constraint on
        accommodation_id."""
        sent = message.model_fields_set
        if "country" in sent or "city" in sent:
            country = Country.get_or_create(
                session, message.country or self.country.name
            )
            self.country_id = country.id
            self.city_id = City.get_or_create(
                session, message.city or self.city.name, country.id
            ).id
        if "street" in sent and message.street is not None:
            self.street = message.street
        if "street_number" in sent:
            self.street_number = message.street_number

    def to_message(self) -> schemas.Location:
        return schemas.Location(
            country=self.country.name,
            city=self.city.name,
            street=self.street,
            street_number=self.street_number,
        )


class RoomDetails(Base):
    __tablename__ = "room_details"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    accommodation_id: Mapped[UUID] = mapped_column(
        ForeignKey("accommodations.id", ondelete="CASCADE"), unique=True
    )
    room_count: Mapped[int | None] = mapped_column(default=None)
    bed_count: Mapped[int | None] = mapped_column(default=None)
    bed_types: Mapped[list[BedType] | None] = mapped_column(
        MutableList.as_mutable(BedTypesJSON), default=None
    )
    description: Mapped[str | None] = mapped_column(default=None)

    accommodation: Mapped[Accommodation] = relationship(back_populates="room_details")

    @classmethod
    def from_message(cls, message: schemas.Room) -> RoomDetails:
        return cls(
            room_count=message.room_count,
            bed_count=message.bed_count,
            bed_types=message.bed_types,
            description=message.description,
        )

    def update_from(self, message: schemas.Room) -> None:
        """Same in-place rule as LocationDetails.update_from."""
        for field in message.model_fields_set:
            value = getattr(message, field)
            if value is not None:
                setattr(self, field, value)

    def to_message(self) -> schemas.Room:
        return schemas.Room.model_validate(self)


class Accommodation(Base):
    __tablename__ = "accommodations"
    # ponytail: no lat/lng on LocationDetails -- add coords only when
    # "within N km" replaces "same city".

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    type: Mapped[AccommodationType] = mapped_column(SAEnum(AccommodationType))
    description: Mapped[str]
    price_per_night: Mapped[Decimal]
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        SAEnum(AvailabilityStatus)
    )
    # Nullable, not zero/empty-defaulted: `exclude_none` is what makes an
    # unset field absent from a response, so a sentinel here would report
    # "unrated" as the real rating 0.0 and "no amenities recorded" as a
    # confirmed empty list. See the API doc's "responses omit what they did
    # not set".
    rating: Mapped[float | None] = mapped_column(default=None)
    amenities: Mapped[list[str] | None] = mapped_column(
        MutableList.as_mutable(JSON), default=None
    )

    location_details: Mapped[LocationDetails] = relationship(
        back_populates="accommodation", uselist=False, cascade="all, delete-orphan"
    )
    room_details: Mapped[RoomDetails | None] = relationship(
        back_populates="accommodation", uselist=False, cascade="all, delete-orphan"
    )

    # --- wire format ------------------------------------------------------
    #
    # `schemas.Accommodation` is one message with every field nullable, so
    # these three methods are the only place that knows which fields an
    # endpoint actually fills in.

    @classmethod
    def from_message(
        cls, session: Session, message: schemas.AccommodationCreateRequest
    ) -> Accommodation:
        """A new row from a create request. The request type is the strict
        subclass, so the fields read here are guaranteed present."""
        return cls(
            name=message.name,
            type=message.type,
            description=message.description,
            price_per_night=message.price_per_night,
            availability_status=message.availability_status,
            rating=message.rating,
            amenities=message.amenities,
            location_details=LocationDetails.from_message(
                session, message.location_details
            ),
            room_details=(
                None
                if message.room_details is None
                else RoomDetails.from_message(message.room_details)
            ),
        )

    def update_from(self, session: Session, message: schemas.Accommodation) -> None:
        """Apply an edit. Only fields the caller actually sent are touched, so
        an omitted field is left alone. An explicit `null` does not clear a
        field either: PUT is documented as a merge, and there is no documented
        way to unset one."""
        nested = {"id", "location_details", "room_details"}
        for field in message.model_fields_set - nested:
            value = getattr(message, field)
            if value is not None:
                setattr(self, field, value)
        if message.location_details is not None:
            self.location_details.update_from(session, message.location_details)
        if message.room_details is not None and self.room_details is not None:
            self.room_details.update_from(message.room_details)

    def to_message(self) -> schemas.Accommodation:
        """The full row as a message. Callers that want the trimmed result-list
        form chain `.summary()` onto this."""
        return schemas.Accommodation(
            id=self.id,
            name=self.name,
            type=self.type,
            description=self.description,
            price_per_night=self.price_per_night,
            availability_status=self.availability_status,
            rating=self.rating,
            amenities=self.amenities,
            location_details=self.location_details.to_message(),
            room_details=(
                None if self.room_details is None else self.room_details.to_message()
            ),
        )
