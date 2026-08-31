"""The accommodation enums, shared by the tables and the wire format.

They live in their own module because `models.py` imports `schemas.py` (for the
message types its conversion methods return) and `schemas.py` needs these -- a
leaf module both can import keeps that a one-way street.
"""

from __future__ import annotations

from enum import Enum


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
