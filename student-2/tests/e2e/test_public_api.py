"""End-to-end tests for the public accommodation API, driven through
TestClient against the real database service over ASGI. Covers the contract in
student-2/docs/backend-service-api.md.

Rows are seeded through the database service's own POST -- this service has no
write path, by design.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend_service import enums as backend_enums
from backend_service import schemas as backend_schemas
from database_service import enums as database_enums
from database_service import schemas as database_schemas
from database_service.seed_data import place as place_ids
from tests.database.test_internal_api import CABIN, HOTEL


@pytest.fixture
def hotel_id(database):
    return database.post("/internal/accommodation", json=HOTEL).json()["id"]


@pytest.fixture
def seeded(database):
    for row in (HOTEL, CABIN):
        database.post("/internal/accommodation", json=row)


def query(client, **filters):
    return client.request("QUERY", "/accommodation", json=filters)


class TestHealth:
    def test_reports_both_services_when_the_database_is_up(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "student-2-backend",
            "database": "ok",
            "location": "ok",
            # The end-to-end chain runs the real database and shared services;
            # AI-Mode is deliberately not part of it, and says so rather than
            # dragging the whole report down to degraded.
            "ai_mode": "not_configured",
        }


class TestGetAccommodation:
    def test_returns_the_full_message(self, client, hotel_id):
        body = client.get(f"/accommodation/{hotel_id}").json()
        assert body["name"] == "example accommodation"
        assert body["price_per_night"] == 1.0
        assert body["amenities"] == ["wifi", "pool"]
        assert body["location_details"]["street_number"] == 123
        assert body["room_details"]["bed_types"] == ["king", "queen"]

    def test_the_message_survives_the_wrapper_unchanged(self, client, database):
        """This service declares the accommodation message separately from the
        database service, so the two have to agree field for field. They are
        the same request one hop apart -- and the only difference allowed is
        the one this service exists to make: the stored country and city ids
        come back as names."""
        row_id = database.post("/internal/accommodation", json=CABIN).json()["id"]
        stored = database.get(f"/internal/accommodation/{row_id}").json()
        published = client.get(f"/accommodation/{row_id}").json()

        place = published.pop("location_details")
        assert place.pop("country") == "australia"
        assert place.pop("city") == "katoomba"
        assert stored.pop("location_details") == {
            **place,
            "country_id": str(place_ids("australia", "katoomba")["country_id"]),
            "city_id": str(place_ids("australia", "katoomba")["city_id"]),
        }
        assert published == stored

    def test_a_relation_the_row_does_not_have_is_absent(self, client, database):
        """The message is one nullable class, so a response says what it means
        by which fields are present."""
        no_rooms = {k: v for k, v in CABIN.items() if k != "room_details"}
        row_id = database.post("/internal/accommodation", json=no_rooms).json()["id"]
        assert "room_details" not in client.get(f"/accommodation/{row_id}").json()

    def test_the_databases_404_reaches_the_caller(self, client):
        response = client.get(f"/accommodation/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "accommodation not found"

    def test_a_non_uuid_id_is_404_not_a_validation_error(self, client):
        assert client.get("/accommodation/garbage").status_code == 404


class TestListAccommodation:
    def test_lists_everything_by_default(self, client, seeded):
        body = client.get("/accommodation").json()
        assert body["total"] == 2
        assert len(body["accommodations"]) == 2

    def test_rows_are_trimmed(self, client, seeded):
        """A list is for choosing which accommodation to GET in full."""
        row = client.get("/accommodation").json()["accommodations"][0]
        assert set(row["location_details"]) == {"country", "city"}
        assert "amenities" not in row
        assert "room_details" not in row

    def test_limit_pages_but_total_counts_every_match(self, client, seeded):
        body = client.get("/accommodation?limit=1").json()
        assert len(body["accommodations"]) == 1
        assert body["total"] == 2

    def test_offset_skips(self, client, seeded):
        first = client.get("/accommodation?limit=1").json()["accommodations"][0]
        second = client.get("/accommodation?limit=1&offset=1").json()["accommodations"][
            0
        ]
        assert first["id"] != second["id"]

    @pytest.mark.parametrize("params", ["limit=0", "limit=101", "offset=-1"])
    def test_out_of_range_paging_is_400_not_422(self, client, params):
        assert client.get(f"/accommodation?{params}").status_code == 400


class TestQueryAccommodation:
    def test_no_filters_returns_everything(self, client, seeded):
        assert query(client).json()["total"] == 2

    def test_filters_stack(self, client, seeded):
        body = query(
            client,
            accommodation={
                "type": "hotel",
                "location_details": {"country": "australia", "city": "sydney"},
            },
            price_max=250,
            room_count_min=2,
        ).json()
        assert [a["name"] for a in body["accommodations"]] == ["example accommodation"]
        assert body["total"] == 1

    def test_city_without_country_is_400(self, client, seeded):
        response = query(client, accommodation={"location_details": {"city": "sydney"}})
        assert response.status_code == 400

    def test_an_unknown_filter_is_400_not_silently_ignored(self, client, seeded):
        assert query(client, room_count_minimum=2).status_code == 400
        assert query(client, accommodation={"contry": "australia"}).status_code == 400

    def test_an_unset_bound_is_not_forwarded_as_null(self, client, seeded):
        """The database service forbids unknown fields but would accept an
        explicit null bound and filter on it, so an all-defaults QUERY must
        still match everything."""
        assert query(client, limit=20).json()["total"] == 2


class TestContract:
    """The two services declare the accommodation message separately, so the
    tests above only catch drift in a field they happen to exercise. These
    compare the declarations directly: every field, every enum value.

    `AccommodationCreateRequest` and `HealthResponse` are deliberately absent
    -- this service has no write path, and its health also reports the
    database.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "Accommodation",
            "Room",
            "AccommodationQueryRequest",
            "AccommodationQueryResponse",
        ],
    )
    def test_the_same_fields(self, name):
        assert set(getattr(backend_schemas, name).model_fields) == set(
            getattr(database_schemas, name).model_fields
        )

    def test_location_is_the_one_message_that_deliberately_differs(self):
        """The database service stores the shared service's ids; this service
        publishes names. That swap is the whole reason this service talks to
        the shared reference service, so the two declarations must *not* match
        -- everything either side of the place fields still has to."""
        published = set(backend_schemas.Location.model_fields)
        stored = set(database_schemas.Location.model_fields)
        assert published - stored == {"country", "city"}
        assert stored - published == {"country_id", "city_id"}

    @pytest.mark.parametrize(
        "name", ["AccommodationType", "AvailabilityStatus", "BedType"]
    )
    def test_the_same_enum_values(self, name):
        assert {m.name: m.value for m in getattr(backend_enums, name)} == {
            m.name: m.value for m in getattr(database_enums, name)
        }


class TestValuesSurviveBothHops:
    """A row written to the database service, read back through this one."""

    @pytest.mark.parametrize(
        "type_", [t.value for t in backend_enums.AccommodationType]
    )
    def test_every_type_is_returned_and_filterable(self, client, database, type_):
        row_id = database.post(
            "/internal/accommodation", json={**HOTEL, "type": type_}
        ).json()["id"]
        assert client.get(f"/accommodation/{row_id}").json()["type"] == type_
        body = query(client, accommodation={"type": type_}).json()
        assert [a["id"] for a in body["accommodations"]] == [row_id]

    @pytest.mark.parametrize(
        "availability", [s.value for s in backend_enums.AvailabilityStatus]
    )
    def test_every_status_and_bed_type(self, client, database, availability):
        beds = [b.value for b in backend_enums.BedType]
        row_id = database.post(
            "/internal/accommodation",
            json={
                **HOTEL,
                "availability_status": availability,
                "room_details": {**HOTEL["room_details"], "bed_types": beds},
            },
        ).json()["id"]
        body = client.get(f"/accommodation/{row_id}").json()
        assert body["availability_status"] == availability
        assert body["room_details"]["bed_types"] == beds

    def test_money_keeps_its_cents(self, client, database):
        """`Decimal` in the database service, `float` here. A price that is not
        a round number is where that difference would show."""
        row_id = database.post(
            "/internal/accommodation", json={**HOTEL, "price_per_night": 189.55}
        ).json()["id"]
        assert (
            client.get(f"/accommodation/{row_id}").json()["price_per_night"] == 189.55
        )
        assert query(client, price_max=189.55).json()["total"] == 1
        assert query(client, price_max=189.54).json()["total"] == 0

    def test_an_update_written_to_the_database_is_visible_here(
        self, client, database, hotel_id
    ):
        """This service has no write path and no cache, so an edit made
        directly on the database service is the next read."""
        database.put(f"/internal/accommodation/{hotel_id}", json={"name": "renamed"})
        assert client.get(f"/accommodation/{hotel_id}").json()["name"] == "renamed"


class TestFiltersReachTheDatabase:
    """Each bound this service publishes, forwarded and actually applied. The
    stacking case above only proves two of them arrive."""

    @pytest.fixture
    def rated(self, database):
        for name, rating, beds in (("good", 4.5, 6), ("poor", 2.0, 1)):
            database.post(
                "/internal/accommodation",
                json={
                    **HOTEL,
                    "name": name,
                    "rating": rating,
                    "room_details": {**HOTEL["room_details"], "bed_count": beds},
                },
            )

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            ({"rating_min": 3}, ["good"]),
            ({"rating_max": 3}, ["poor"]),
            ({"price_min": 2}, []),
            ({"bed_count_min": 6}, ["good"]),
        ],
    )
    def test_a_bound_narrows_the_result(self, client, rated, filters, expected):
        body = query(client, **filters).json()
        assert [a["name"] for a in body["accommodations"]] == expected
        assert body["total"] == len(expected)
