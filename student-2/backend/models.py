from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from shared.backend.models import Booking


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


@dataclass
class RoomDetails:
    room_count: int
    bed_count: int
    bed_types: list[BedType] = field(default_factory=list)
    description: str = ""


@dataclass
class Accommodation:
    id: UUID
    name: str
    type: AccommodationType
    location: str
    description: str
    price_per_night: Decimal
    availability_status: AvailabilityStatus
    rating: float = 0.0
    amenities: list[str] = field(default_factory=list)
    room_details: RoomDetails | None = None


@dataclass(kw_only=True)
class AccommodationBooking(Booking):
    trip_id: UUID  # external FK, owned by Student 1's Trip service
    accommodation_id: UUID
    check_in_date: date
    check_out_date: date
    num_guests: int


@dataclass
class AccommodationRating:
    id: UUID
    accommodation_id: UUID
    user_id: UUID
    score: int  # 1-5
    comment: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
