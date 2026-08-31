"""Accommodation microservice ORM models.

See ../../docs/object-model.md for the design (entities + ERD).
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, UniqueConstraint, event
from sqlalchemy import Enum as SAEnum
from sqlalchemy.engine import Engine
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base every ORM model in this service inherits from."""


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite ships with FK enforcement off, so RESTRICT below is a no-op
    without this. Applies to every engine, including the test fixtures'."""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


class AccommodationType(Enum):
    HOTEL = "hotel"
    HOSTEL = "hostel"
    APARTMENT = "apartment"
    RESORT = "resort"
    GUESTHOUSE = "guesthouse"
    CAMPING = "camping"


class AvailabilityStatus(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    SOLD_OUT = "sold_out"


class BedType(Enum):
    SINGLE = "single"
    DOUBLE = "double"
    QUEEN = "queen"
    KING = "king"
    BUNK = "bunk"
    SOFA_BED = "sofa_bed"


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
            return []
        return [BedType(v) for v in value]


class Country(Base):
    """Reference list of countries -- just a name, nothing else."""

    __tablename__ = "countries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(unique=True)


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
    street: Mapped[str] = mapped_column(default="")
    street_number: Mapped[int | None] = mapped_column(default=None)

    accommodation: Mapped[Accommodation] = relationship(
        back_populates="location_details"
    )
    country: Mapped[Country] = relationship()
    city: Mapped[City] = relationship()


class RoomDetails(Base):
    __tablename__ = "room_details"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    accommodation_id: Mapped[UUID] = mapped_column(
        ForeignKey("accommodations.id", ondelete="CASCADE"), unique=True
    )
    room_count: Mapped[int]
    bed_count: Mapped[int]
    bed_types: Mapped[list[BedType]] = mapped_column(
        MutableList.as_mutable(BedTypesJSON), default=list
    )
    description: Mapped[str] = mapped_column(default="")

    accommodation: Mapped[Accommodation] = relationship(back_populates="room_details")


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
    rating: Mapped[float] = mapped_column(default=0.0)
    amenities: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )

    location_details: Mapped[LocationDetails] = relationship(
        back_populates="accommodation", uselist=False, cascade="all, delete-orphan"
    )
    room_details: Mapped[RoomDetails | None] = relationship(
        back_populates="accommodation", uselist=False, cascade="all, delete-orphan"
    )
