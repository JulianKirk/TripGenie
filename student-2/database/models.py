"""Accommodation microservice ORM models.

See ../../docs/architecture/object-model.md for the design (entities + ERD).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, event
from sqlalchemy import Enum as SAEnum
from sqlalchemy.engine import Engine
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from shared.backend.models import Base


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


class AccommodationBookingStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


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
    # The itinerary service asks "what can I stay in at <place>", so city and
    # country are the query keys and get the index; address is display-only.
    # ponytail: no state/postcode/lat-lng and no Location table -- add coords
    # only when "within N km" replaces "same city".
    __table_args__ = (Index("ix_accommodations_city", "country", "city"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    type: Mapped[AccommodationType] = mapped_column(SAEnum(AccommodationType))
    country: Mapped[str]
    city: Mapped[str]
    address: Mapped[str] = mapped_column(default="")
    description: Mapped[str]
    price_per_night: Mapped[Decimal]
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        SAEnum(AvailabilityStatus)
    )
    rating: Mapped[float] = mapped_column(default=0.0)
    amenities: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )

    room_details: Mapped[RoomDetails | None] = relationship(
        back_populates="accommodation", uselist=False, cascade="all, delete-orphan"
    )
    # RESTRICT: delete the bookings/ratings first, the DB refuses otherwise.
    # passive_deletes="all" stops the ORM nulling the FK out from under it.
    bookings: Mapped[list[AccommodationBooking]] = relationship(passive_deletes="all")
    ratings: Mapped[list[AccommodationRating]] = relationship(passive_deletes="all")


class AccommodationBooking(Base):
    __tablename__ = "accommodation_bookings"
    __table_args__ = (
        CheckConstraint("check_out_date > check_in_date", name="ck_booking_dates"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID]
    trip_id: Mapped[UUID]  # external FK, owned by Student 1's Trip service
    accommodation_id: Mapped[UUID] = mapped_column(
        ForeignKey("accommodations.id", ondelete="RESTRICT")
    )
    check_in_date: Mapped[date]
    check_out_date: Mapped[date]
    num_guests: Mapped[int]
    cost: Mapped[Decimal]
    status: Mapped[AccommodationBookingStatus] = mapped_column(
        SAEnum(AccommodationBookingStatus),
        default=AccommodationBookingStatus.PENDING,
    )


class AccommodationRating(Base):
    __tablename__ = "accommodation_ratings"
    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="ck_rating_score"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    accommodation_id: Mapped[UUID] = mapped_column(
        ForeignKey("accommodations.id", ondelete="RESTRICT")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int]  # 1-5
    comment: Mapped[str] = mapped_column(default="")
    # ponytail: naive UTC -- SQLite's DATETIME drops the offset on the way
    # back out, so storing tz-aware just yields naive rows anyway.
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
