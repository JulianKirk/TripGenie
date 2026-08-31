"""Tests for the repository layer. Run `pytest student-2/tests` from the
repo root.

Grouped into Test* classes so an IDE (or `pytest -k`) can run one
repository's tests as a unit. Plain classes -- no base class, no __init__ --
fixtures are still just method arguments.
"""

from __future__ import annotations

from uuid import uuid4

from database_service.models import BedType
from database_service.schemas import AccommodationQueryRequest
from database_service.seed_data import SEED_ACCOMMODATIONS, seed


class TestAccommodationRepository:
    def test_add_and_get(self, accommodations, hotel):
        assert accommodations.get(hotel.id).name == "Grand Hotel"

    def test_search_without_filters_returns_everything(
        self, accommodations, camping, hotel
    ):
        rows, total = accommodations.search(AccommodationQueryRequest())
        assert {a.name for a in rows} == {"Cosy Cabin", "Grand Hotel"}
        assert total == 2

    def test_bed_types_round_trip_as_enum_members(self, accommodations, hotel):
        reloaded = accommodations.get(hotel.id)
        assert reloaded.room_details.bed_types == [BedType.QUEEN, BedType.KING]
        assert all(isinstance(bt, BedType) for bt in reloaded.room_details.bed_types)

    def test_search_by_room_count_range(self, accommodations, camping, hotel):
        """SQL-level range filter via the RoomDetails join."""
        rows, total = accommodations.search(
            AccommodationQueryRequest(room_count_min=10)
        )
        assert [a.name for a in rows] == ["Grand Hotel"]
        assert total == 1

    def test_search_by_city(self, accommodations, camping, hotel):
        rows, _ = accommodations.search(
            AccommodationQueryRequest(
                accommodation={
                    "location_details": {"country": "Australia", "city": "Sydney"}
                }
            )
        )
        assert [a.name for a in rows] == ["Grand Hotel"]

    def test_search_filters_stack(self, accommodations, camping, hotel):
        """The case the two old single-purpose methods could not express."""
        rows, total = accommodations.search(
            AccommodationQueryRequest(
                accommodation={
                    "location_details": {"country": "Australia", "city": "Sydney"}
                },
                room_count_min=10,
            )
        )
        assert [a.name for a in rows] == ["Grand Hotel"]
        assert total == 1

        rows, total = accommodations.search(
            AccommodationQueryRequest(
                accommodation={
                    "location_details": {"country": "Australia", "city": "Katoomba"}
                },
                room_count_min=10,
            )
        )
        assert rows == []
        assert total == 0

    def test_search_by_price_ceiling(self, accommodations, camping, hotel):
        """A range with only one end set leaves the other open."""
        rows, _ = accommodations.search(AccommodationQueryRequest(price_max=100))
        assert [a.name for a in rows] == ["Cosy Cabin"]

    def test_search_by_enum_equality(self, accommodations, camping, hotel):
        rows, _ = accommodations.search(
            AccommodationQueryRequest(accommodation={"type": "camping"})
        )
        assert [a.name for a in rows] == ["Cosy Cabin"]

    def test_search_paginates_but_totals_the_whole_match(
        self, accommodations, camping, hotel
    ):
        """`total` counts every match, not just the page returned."""
        rows, total = accommodations.search(AccommodationQueryRequest(limit=1))
        assert len(rows) == 1
        assert total == 2

    def test_search_by_name_matches_a_substring_case_insensitively(
        self, accommodations, camping, hotel
    ):
        """What the frontend's search box sends -- half a word, any case."""
        rows, total = accommodations.search(
            AccommodationQueryRequest(accommodation={"name": "and hot"})
        )
        assert [a.name for a in rows] == ["Grand Hotel"]
        assert total == 1

    def test_search_by_description_matches_a_substring(
        self, accommodations, camping, hotel
    ):
        rows, _ = accommodations.search(
            AccommodationQueryRequest(accommodation={"description": "TENT"})
        )
        assert [a.name for a in rows] == ["Cosy Cabin"]

    def test_search_by_amenities_wants_every_one_of_them(
        self, session, accommodations, camping, hotel
    ):
        hotel.amenities = ["wifi", "pool"]
        camping.amenities = ["wifi"]
        session.commit()

        both = AccommodationQueryRequest(accommodation={"amenities": ["wifi", "pool"]})
        one = AccommodationQueryRequest(accommodation={"amenities": ["wifi"]})
        assert [a.name for a in accommodations.search(both)[0]] == ["Grand Hotel"]
        assert accommodations.search(one)[1] == 2

    def test_an_amenity_is_matched_whole_not_as_a_prefix(
        self, session, accommodations, hotel
    ):
        hotel.amenities = ["wifi6"]
        session.commit()
        query = AccommodationQueryRequest(accommodation={"amenities": ["wifi"]})
        assert accommodations.search(query)[1] == 0

    def test_pages_do_not_repeat_a_row(self, accommodations, camping, hotel):
        """Without an ORDER BY, LIMIT/OFFSET may hand back the same row twice."""
        first, _ = accommodations.search(AccommodationQueryRequest(limit=1))
        second, _ = accommodations.search(AccommodationQueryRequest(limit=1, offset=1))
        assert [a.name for a in first] == ["Cosy Cabin"]
        assert [a.name for a in second] == ["Grand Hotel"]

    def test_delete(self, accommodations, camping, hotel):
        accommodations.delete(camping.id)
        assert accommodations.get(camping.id) is None
        assert accommodations.search(AccommodationQueryRequest())[1] == 1

    def test_delete_missing_id_is_a_noop(self, accommodations, hotel):
        accommodations.delete(uuid4())
        assert accommodations.search(AccommodationQueryRequest())[1] == 1


class TestSeedData:
    def test_seeds_an_empty_database_once(self, session, accommodations):
        assert seed(session) == len(SEED_ACCOMMODATIONS)
        assert accommodations.search(AccommodationQueryRequest(limit=100))[1] == len(
            SEED_ACCOMMODATIONS
        )

    def test_a_database_with_rows_is_left_alone(self, session, accommodations, hotel):
        assert seed(session) == 0
        assert accommodations.search(AccommodationQueryRequest())[1] == 1
