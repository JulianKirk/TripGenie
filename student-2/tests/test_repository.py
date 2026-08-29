"""Tests for the repository layer. Run `pytest student-2/tests` from the
repo root (import paths come from pytest.ini's `pythonpath`).

Grouped into Test* classes so an IDE (or `pytest -k`) can run one
repository's tests as a unit. Plain classes -- no base class, no __init__ --
fixtures are still just method arguments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from database.models import (
    AccommodationBooking,
    AccommodationBookingStatus,
    AccommodationRating,
    BedType,
)


class TestAccommodationRepository:
    def test_add_and_get(self, accommodations, hotel):
        assert accommodations.get(hotel.id).name == "Grand Hotel"

    def test_list(self, accommodations, camping, hotel):
        assert {a.name for a in accommodations.list()} == {"Cosy Cabin", "Grand Hotel"}

    def test_bed_types_round_trip_as_enum_members(self, accommodations, hotel):
        reloaded = accommodations.get(hotel.id)
        assert reloaded.room_details.bed_types == [BedType.QUEEN, BedType.KING]
        assert all(isinstance(bt, BedType) for bt in reloaded.room_details.bed_types)

    def test_list_by_min_room_count(self, accommodations, camping, hotel):
        """SQL-level filter via the RoomDetails join."""
        filtered = accommodations.list_by_min_room_count(10)
        assert [a.name for a in filtered] == ["Grand Hotel"]

    def test_delete(self, accommodations, camping, hotel):
        accommodations.delete(camping.id)
        assert accommodations.get(camping.id) is None
        assert len(accommodations.list()) == 1

    def test_delete_missing_id_is_a_noop(self, accommodations, hotel):
        accommodations.delete(uuid4())
        assert len(accommodations.list()) == 1


class TestAccommodationBookingRepository:
    def test_booking_defaults_to_pending(self, bookings, user, hotel):
        booking = bookings.add(
            AccommodationBooking(
                id=uuid4(),
                owner_id=user.id,
                cost=Decimal("500.00"),
                trip_id=uuid4(),
                accommodation_id=hotel.id,
                check_in_date=date(2026, 1, 1),
                check_out_date=date(2026, 1, 3),
                num_guests=2,
            )
        )
        assert bookings.get(booking.id).status is AccommodationBookingStatus.PENDING


class TestAccommodationRatingRepository:
    def test_rating(self, ratings, user, hotel):
        rating = ratings.add(
            AccommodationRating(
                id=uuid4(), accommodation_id=hotel.id, user_id=user.id, score=5
            )
        )
        assert ratings.get(rating.id).score == 5
