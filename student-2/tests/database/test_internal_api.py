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


class TestRouting:
    def test_a_non_uuid_id_is_404_not_a_validation_error(self, client):
        assert client.get("/accommodation/garbage").status_code == 404


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

    def test_a_missing_required_field_is_400(self, client):
        """Every field on the message is nullable, so the strict create
        subclass is the only thing standing between POST {} and a row with no
        name. It has to name each field it rejected."""
        response = client.post("/accommodation", json={})
        assert response.status_code == 400
        missing = {tuple(e["loc"])[-1] for e in response.json()["detail"]}
        assert missing == {
            "name",
            "type",
            "description",
            "price_per_night",
            "availability_status",
            "location_details",
        }

    def test_the_create_response_carries_only_what_it_populated(self, client):
        """One nullable message serves every endpoint, so a response says what
        it means by which fields are present -- not by sending nulls."""
        body = client.post("/accommodation", json=HOTEL).json()
        assert set(body) == {"id", "name"}

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
            "QUERY",
            "/accommodation",
            json={
                "accommodation": {
                    "location_details": {"country": "australia", "city": "sydney"}
                }
            },
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
            client,
            accommodation={
                "location_details": {"country": "australia", "city": "sydney"}
            },
            room_count_min=2,
        ).json()
        assert [a["name"] for a in body["accommodations"]] == ["example accommodation"]
        assert body["total"] == 1

    def test_summary_omits_the_heavy_fields(self, client):
        row = self.query(
            client,
            accommodation={
                "location_details": {"country": "australia", "city": "sydney"}
            },
        ).json()["accommodations"][0]
        assert set(row["location_details"]) == {"country", "city"}
        assert "amenities" not in row

    def test_limit_pages_but_total_counts_every_match(self, client):
        body = self.query(client, limit=1).json()
        assert len(body["accommodations"]) == 1
        assert body["total"] == 2

    def test_matches_a_range_and_the_template_together(self, client):
        body = self.query(client, accommodation={"type": "hotel"}, price_max=250).json()
        assert [a["name"] for a in body["accommodations"]] == ["example accommodation"]

    def test_city_without_country_is_400(self, client):
        response = self.query(
            client, accommodation={"location_details": {"city": "sydney"}}
        )
        assert response.status_code == 400

    def test_an_unknown_filter_is_400_not_silently_ignored(self, client):
        assert self.query(client, room_count_minimum=2).status_code == 400
        nested = self.query(client, accommodation={"contry": "australia"})
        assert nested.status_code == 400


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

    def test_update_location_details(self, client, hotel_id):
        """Updating location should not cause UNIQUE constraint failure."""
        response = client.put(
            f"/accommodation/{hotel_id}",
            json={
                "location_details": {
                    "country": "australia",
                    "city": "melbourne",
                    "street": "new street",
                    "street_number": 999,
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["location_details"]["city"] == "melbourne"
        assert body["location_details"]["street"] == "new street"
        assert body["location_details"]["street_number"] == 999

    def test_update_room_details(self, client, hotel_id):
        """Updating room should preserve related data."""
        response = client.put(
            f"/accommodation/{hotel_id}",
            json={"room_details": {"room_count": 10, "bed_count": 15}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["room_details"]["room_count"] == 10
        assert body["room_details"]["bed_count"] == 15
        # bed_types should still be there from the fixture
        assert set(body["room_details"]["bed_types"]) == {"king", "queen"}
