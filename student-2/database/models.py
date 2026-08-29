"""Accommodation microservice ORM models.

See ../../docs/architecture/object-model.md for the design (entities + ERD).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from shared.backend.models import Base


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
    accommodation_id: Mapped[UUID] = mapped_column(ForeignKey("accommodations.id"))
    room_count: Mapped[int]
    bed_count: Mapped[int]
    bed_types: Mapped[list[BedType]] = mapped_column(BedTypesJSON, default=list)
    description: Mapped[str] = mapped_column(default="")

    accommodation: Mapped[Accommodation] = relationship(back_populates="room_details")


class Accommodation(Base):
    __tablename__ = "accommodations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    type: Mapped[AccommodationType] = mapped_column(SAEnum(AccommodationType))
    location: Mapped[str]
    description: Mapped[str]
    price_per_night: Mapped[Decimal]
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        SAEnum(AvailabilityStatus)
    )
    rating: Mapped[float] = mapped_column(default=0.0)
    amenities: Mapped[list[str]] = mapped_column(JSON, default=list)

    room_details: Mapped[RoomDetails | None] = relationship(
        back_populates="accommodation", uselist=False, cascade="all, delete-orphan"
    )


class AccommodationBooking(Base):
    __tablename__ = "accommodation_bookings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID]
    trip_id: Mapped[UUID]  # external FK, owned by Student 1's Trip service
    accommodation_id: Mapped[UUID] = mapped_column(ForeignKey("accommodations.id"))
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

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    accommodation_id: Mapped[UUID] = mapped_column(ForeignKey("accommodations.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int]  # 1-5
    comment: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
