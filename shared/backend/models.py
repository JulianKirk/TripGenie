"""Models shared across TripGenie microservices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


@dataclass
class User:
    user_id: UUID
    name: str
    email: str


class BookingStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(kw_only=True)
class Booking:
    """Base for any per-service booking (accommodation, transport, activity, ...)."""
    id: UUID
    owner_id: UUID
    cost: Decimal
    status: BookingStatus = BookingStatus.PENDING
