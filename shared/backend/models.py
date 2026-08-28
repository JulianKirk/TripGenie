"""Models shared across TripGenie microservices."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base every ORM model in the project inherits from."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    email: Mapped[str]


class BookingStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Booking:
    """Mixin for any per-service booking (accommodation, transport, activity, ...).

    Not mapped/Base-derived itself -- each service's concrete booking table
    (e.g. AccommodationBooking) combines this with Base, since bookings for
    different services live in different tables/databases, not one shared one.
    """

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID]
    cost: Mapped[Decimal]
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus), default=BookingStatus.PENDING
    )
