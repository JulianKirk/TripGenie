"""End-to-end tests for the HTTP layer, driven through TestClient against a
real (temporary) SQLite file -- the same path the container takes, minus the
network. Covers the contract in student-2/docs/database-service-api.md.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from database_service.app import create_app
from database_service.config import Settings

HOTEL = {
    "name": "example accommodation",
    "type": "hotel",
    "description": "an exemplary hotel for all your travel adventures",
    "price_per_night": 1.00,
    "availability_status": "available",
    "amenities": ["wifi", "pool"],
    "location_details": {
        "country": "australia",
        "city": "sydney",
        "street": "example street avenue",
        "street_number": 123,
    },
    "room_details": {
        "room_count": 3,
        "bed_count": 2,
        "bed_types": ["king", "queen"],
        "description": "three bedroom hotel space with big beds",
    },
}

CABIN = {
    **HOTEL,
    "name": "cosy cabin",
    "type": "camping",
    "location_details": {"country": "australia", "city": "katoomba"},
    "room_details": {"room_count": 1, "bed_count": 1},
}


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'accommodation.db'}")
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def hotel_id(client):
    return client.post("/accommodation", json=HOTEL).json()["id"]


class TestHealth:
    def test_ok_on_an_empty_database(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "student-2-database"}


class TestAccommodation:
    def test_create_returns_201_with_id_and_name(self, client):
        response = client.post("/accommodation", json=HOTEL)
        assert response.status_code == 201
        assert response.json()["name"] == "example accommodation"

    def test_round_trip(self, client, hotel_id):
        body = client.get(f"/accommodation/{hotel_id}").json()
        assert body["type"] == "hotel"
        assert body["amenities"] == ["wifi", "pool"]
        assert body["location_details"]["city"] == "sydney"
        assert body["location_details"]["street_number"] == 123
        assert body["room_details"]["bed_types"] == ["king", "queen"]

    def test_money_is_a_json_number_not_a_string(self, client, hotel_id):
        """Decimal round-trips through pydantic as a string unless told
        otherwise, and the API doc shows `1.00`."""
        assert client.get(f"/accommodation/{hotel_id}").json()["price_per_night"] == 1.0

    def test_unknown_id_is_404(self, client):
        assert client.get(f"/accommodation/{uuid4()}").status_code == 404

    def test_malformed_enum_is_400_not_422(self, client):
        response = client.post("/accommodation", json={**HOTEL, "type": "igloo"})
        assert response.status_code == 400

    def test_country_and_city_are_reused_not_duplicated(self, client):
        """Two accommodations in the same city must not create two City rows --
        the second POST looks the first one's up by name."""
        first = client.post("/accommodation", json=HOTEL).json()["id"]
        second = client.post("/accommodation", json={**HOTEL, "name": "other"}).json()[
            "id"
        ]
        cities = {
            client.get(f"/accommodation/{i}").json()["location_details"]["city"]
            for i in (first, second)
        }
        assert cities == {"sydney"}

        rows = client.request(
            "QUERY", "/accommodation", json={"country": "australia", "city": "sydney"}
        ).json()
        assert rows["total"] == 2


class TestAccommodationQuery:
    @pytest.fixture(autouse=True)
    def _seed(self, client):
        client.post("/accommodation", json=HOTEL)
        client.post("/accommodation", json=CABIN)

    def query(self, client, **filters):
        return client.request("QUERY", "/accommodation", json=filters)

    def test_no_filters_returns_everything(self, client):
        assert self.query(client).json()["total"] == 2

    def test_filters_stack(self, client):
        body = self.query(
            client, country="australia", city="sydney", min_room_count=2
        ).json()
        assert [a["name"] for a in body["accommodations"]] == ["example accommodation"]
        assert body["total"] == 1

    def test_summary_omits_the_heavy_fields(self, client):
        row = self.query(client, city="sydney", country="australia").json()[
            "accommodations"
        ][0]
        assert set(row["location_details"]) == {"country", "city"}
        assert "amenities" not in row

    def test_limit_pages_but_total_counts_every_match(self, client):
        body = self.query(client, limit=1).json()
        assert len(body["accommodations"]) == 1
        assert body["total"] == 2

    def test_city_without_country_is_400(self, client):
        assert self.query(client, city="sydney").status_code == 400


class TestAccommodationUpdate:
    def test_partial_update_leaves_other_fields_alone(self, client, hotel_id):
        response = client.put(
            f"/accommodation/{hotel_id}",
            json={"price_per_night": 250.00, "availability_status": "sold_out"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["price_per_night"] == 250.0
        assert body["availability_status"] == "sold_out"
        assert body["name"] == "example accommodation"
        assert body["amenities"] == ["wifi", "pool"]

    def test_unknown_id_is_404(self, client):
        response = client.put(f"/accommodation/{uuid4()}", json={"name": "x"})
        assert response.status_code == 404


class TestBooking:
    @pytest.fixture
    def booking(self, client, hotel_id):
        return client.post(
            "/accommodation/booking",
            json={
                "owner_id": str(uuid4()),
                "trip_id": str(uuid4()),
                "accommodation_id": hotel_id,
                "check_in_date": "2026-09-01T14:00:00",
                "check_out_date": "2026-09-05T10:00:00",
                "num_guests": 2,
                "cost": 1000.00,
            },
        )

    def test_create_defaults_to_pending(self, booking):
        assert booking.status_code == 201
        assert booking.json()["status"] == "pending"

    def test_round_trip(self, client, booking):
        body = client.get(f"/accommodation/booking/{booking.json()['id']}").json()
        assert body["num_guests"] == 2
        assert body["cost"] == 1000.0
        assert body["check_in_date"] == "2026-09-01T14:00:00"

    def test_list(self, client, booking):
        body = client.get("/accommodation/booking?limit=10").json()
        assert body["total"] == 1
        assert set(body["bookings"][0]) == {
            "id",
            "accommodation_id",
            "check_in_date",
            "check_out_date",
            "status",
        }

    def test_check_out_before_check_in_is_400(self, client, hotel_id):
        response = client.post(
            "/accommodation/booking",
            json={
                "owner_id": str(uuid4()),
                "trip_id": str(uuid4()),
                "accommodation_id": hotel_id,
                "check_in_date": "2026-09-05T10:00:00",
                "check_out_date": "2026-09-01T14:00:00",
                "num_guests": 2,
                "cost": 1000.00,
            },
        )
        assert response.status_code == 400

    def test_unknown_accommodation_is_404(self, client):
        response = client.post(
            "/accommodation/booking",
            json={
                "owner_id": str(uuid4()),
                "trip_id": str(uuid4()),
                "accommodation_id": str(uuid4()),
                "check_in_date": "2026-09-01T14:00:00",
                "check_out_date": "2026-09-05T10:00:00",
                "num_guests": 2,
                "cost": 1000.00,
            },
        )
        assert response.status_code == 404

    def test_delete_then_get_is_404(self, client, booking):
        booking_id = booking.json()["id"]
        assert client.delete(f"/accommodation/booking/{booking_id}").status_code == 204
        assert client.get(f"/accommodation/booking/{booking_id}").status_code == 404

    def test_delete_unknown_is_404(self, client):
        assert client.delete(f"/accommodation/booking/{uuid4()}").status_code == 404


class TestRating:
    @pytest.fixture
    def rating(self, client, hotel_id):
        return client.post(
            "/accommodation/rating",
            json={
                "accommodation_id": hotel_id,
                "user_id": str(uuid4()),
                "score": 5,
                "comment": "Fantastic stay, would book again.",
            },
        )

    def test_create(self, rating):
        assert rating.status_code == 201
        assert rating.json()["score"] == 5

    def test_round_trip(self, client, rating):
        body = client.get(f"/accommodation/rating/{rating.json()['id']}").json()
        assert body["comment"] == "Fantastic stay, would book again."
        assert body["created_at"]

    def test_list(self, client, rating):
        body = client.get("/accommodation/rating?limit=10").json()
        assert body["total"] == 1
        assert body["ratings"][0]["score"] == 5

    def test_score_out_of_range_is_400(self, client, hotel_id):
        response = client.post(
            "/accommodation/rating",
            json={
                "accommodation_id": hotel_id,
                "user_id": str(uuid4()),
                "score": 6,
            },
        )
        assert response.status_code == 400

    def test_unknown_accommodation_is_404(self, client):
        response = client.post(
            "/accommodation/rating",
            json={
                "accommodation_id": str(uuid4()),
                "user_id": str(uuid4()),
                "score": 5,
            },
        )
        assert response.status_code == 404

    def test_delete_then_get_is_404(self, client, rating):
        rating_id = rating.json()["id"]
        assert client.delete(f"/accommodation/rating/{rating_id}").status_code == 204
        assert client.get(f"/accommodation/rating/{rating_id}").status_code == 404
