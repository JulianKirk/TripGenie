"""Self-check for the repository layer. Run directly:

    student-2/backend/.venv/bin/python student-2/tests/test_repository.py

Import paths (repo root for `shared`, student-2 for `backend`) come from
tripgenie-root.pth in the venv's site-packages -- no PYTHONPATH needed.

Uses an in-memory SQLite DB -- no dependency on database.py's file default.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import (
    Accommodation,
    AccommodationBooking,
    AccommodationRating,
    AccommodationType,
    AvailabilityStatus,
    BedType,
    RoomDetails,
)
from backend.repository import (
    AccommodationBookingRepository,
    AccommodationRatingRepository,
    AccommodationRepository,
)
from shared.backend.models import Base, User


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)

    accommodations = AccommodationRepository(session)
    bookings = AccommodationBookingRepository(session)
    ratings = AccommodationRatingRepository(session)

    user = User(id=uuid4(), name="Mark", email="mark@example.com")
    session.add(user)
    session.commit()

    small = Accommodation(
        id=uuid4(),
        name="Cosy Cabin",
        type=AccommodationType.CAMPING,
        location="Blue Mountains",
        description="tent site",
        price_per_night=Decimal("20.00"),
        availability_status=AvailabilityStatus.AVAILABLE,
        room_details=RoomDetails(room_count=1, bed_count=1, bed_types=[BedType.SINGLE]),
    )
    big = Accommodation(
        id=uuid4(),
        name="Grand Hotel",
        type=AccommodationType.HOTEL,
        location="Sydney",
        description="city hotel",
        price_per_night=Decimal("250.00"),
        availability_status=AvailabilityStatus.AVAILABLE,
        room_details=RoomDetails(
            room_count=40, bed_count=60, bed_types=[BedType.QUEEN, BedType.KING]
        ),
    )
    accommodations.add(small)
    accommodations.add(big)

    # add/get/list
    assert accommodations.get(big.id).name == "Grand Hotel"
    assert {a.name for a in accommodations.list()} == {"Cosy Cabin", "Grand Hotel"}

    # bed_types round-trip through the DB as real BedType enum members
    reloaded = accommodations.get(big.id)
    assert reloaded.room_details.bed_types == [BedType.QUEEN, BedType.KING]
    assert all(isinstance(bt, BedType) for bt in reloaded.room_details.bed_types)

    # filter by room_count (SQL-level, via RoomDetails join)
    filtered = accommodations.list_by_min_room_count(10)
    assert [a.name for a in filtered] == ["Grand Hotel"]

    # booking, inherited fields (id/owner_id/cost/status) from the Booking mixin
    booking = AccommodationBooking(
        id=uuid4(),
        owner_id=user.id,
        cost=Decimal("500.00"),
        trip_id=uuid4(),
        accommodation_id=big.id,
        check_in_date=date(2026, 1, 1),
        check_out_date=date(2026, 1, 3),
        num_guests=2,
    )
    bookings.add(booking)
    assert bookings.get(booking.id).status.value == "pending"

    # rating
    rating = AccommodationRating(
        id=uuid4(), accommodation_id=big.id, user_id=user.id, score=5
    )
    ratings.add(rating)
    assert ratings.get(rating.id).score == 5

    # delete
    accommodations.delete(small.id)
    assert accommodations.get(small.id) is None
    assert len(accommodations.list()) == 1

    session.close()
    print("all repository checks passed")


if __name__ == "__main__":
    main()
