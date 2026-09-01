"""End-to-end tests for the HTTP layer, driven through TestClient against a
real (temporary) SQLite file -- the same path the container takes, minus the
network. Covers the contract in shared/docs/database-service-api.md.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from shared_database_service import ids
from shared_database_service.app import create_app
from shared_database_service.config import Settings

COUNTRY = "/internal/location/country"
CITY = "/internal/location/city"


@pytest.fixture
def client(tmp_path):
    """The real app on a temporary SQLite file, unseeded -- these tests assert
    on exact counts of rows they created themselves."""
    app = create_app(
        Settings(database_url=f"sqlite:///{tmp_path / 'location.db'}", seed=False)
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def australia(client):
    return client.post(COUNTRY, json={"name": "australia"}).json()


class TestHealth:
    def test_reports_the_service_name(self, client):
        assert client.get("/health").json() == {
            "status": "ok",
            "service": "shared-database",
        }


class TestCreateCountry:
    def test_returns_201_and_the_derived_id(self, client):
        response = client.post(COUNTRY, json={"name": "australia"})
        assert response.status_code == 201
        assert response.json() == {
            "id": str(ids.country_id("australia")),
            "name": "australia",
        }

    def test_creating_the_same_country_twice_returns_200(self, client, australia):
        response = client.post(COUNTRY, json={"name": "Australia"})
        assert response.status_code == 200
        assert response.json()["id"] == australia["id"]

    def test_missing_name_is_400(self, client):
        assert client.post(COUNTRY, json={}).status_code == 400

    def test_unknown_field_is_400(self, client):
        assert (
            client.post(COUNTRY, json={"name": "x", "capital": "y"}).status_code == 400
        )


class TestGetCountry:
    def test_returns_the_row(self, client, australia):
        response = client.get(f"{COUNTRY}/{australia['id']}")
        assert response.status_code == 200
        assert response.json() == australia

    def test_missing_is_404(self, client):
        assert client.get(f"{COUNTRY}/{uuid4()}").status_code == 404

    def test_malformed_id_does_not_match_the_route(self, client):
        # The `:uuid` convertor, so a junk id is a 404 rather than a 400.
        assert client.get(f"{COUNTRY}/not-a-uuid").status_code == 404


class TestQueryCountry:
    def test_no_filters_returns_everything(self, client, australia):
        client.post(COUNTRY, json={"name": "japan"})
        body = client.request("QUERY", COUNTRY, json={}).json()
        assert body["total"] == 2

    def test_name_matches_a_substring(self, client, australia):
        client.post(COUNTRY, json={"name": "japan"})
        body = client.request(
            "QUERY", COUNTRY, json={"country": {"name": "AUSTRAL"}}
        ).json()
        assert body["countries"] == [australia]
        assert body["total"] == 1

    def test_unknown_field_is_400(self, client):
        response = client.request("QUERY", COUNTRY, json={"nope": 1})
        assert response.status_code == 400


class TestCreateCity:
    def test_returns_201_and_the_derived_id(self, client, australia):
        response = client.post(
            CITY, json={"name": "sydney", "country_id": australia["id"]}
        )
        assert response.status_code == 201
        assert response.json() == {
            "id": str(ids.city_id("australia", "sydney")),
            "name": "sydney",
            "country_id": australia["id"],
        }

    def test_creating_the_same_city_twice_returns_200(self, client, australia):
        payload = {"name": "sydney", "country_id": australia["id"]}
        client.post(CITY, json=payload)
        assert client.post(CITY, json=payload).status_code == 200

    def test_unknown_country_is_404(self, client):
        response = client.post(
            CITY, json={"name": "sydney", "country_id": str(uuid4())}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "country not found"

    def test_missing_country_is_400(self, client):
        assert client.post(CITY, json={"name": "sydney"}).status_code == 400


class TestQueryCity:
    def test_filters_by_country(self, client, australia):
        japan = client.post(COUNTRY, json={"name": "japan"}).json()
        client.post(CITY, json={"name": "sydney", "country_id": australia["id"]})
        client.post(CITY, json={"name": "tokyo", "country_id": japan["id"]})
        body = client.request(
            "QUERY", CITY, json={"city": {"country_id": japan["id"]}}
        ).json()
        assert [city["name"] for city in body["cities"]] == ["tokyo"]
        assert body["total"] == 1

    def test_pages(self, client, australia):
        for name in ("sydney", "melbourne", "brisbane"):
            client.post(CITY, json={"name": name, "country_id": australia["id"]})
        body = client.request("QUERY", CITY, json={"limit": 2}).json()
        assert body["total"] == 3
        assert [city["name"] for city in body["cities"]] == ["brisbane", "melbourne"]


class TestSeed:
    def test_a_seeded_database_carries_the_places_other_services_reference(
        self, tmp_path
    ):
        """Student 2's seeded accommodations point at these ids offline, so a
        missing row here leaves those rows unnameable."""
        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'seeded.db'}"))
        with TestClient(app) as client:
            for country, city in (
                ("australia", "sydney"),
                ("japan", "tokyo"),
                ("new zealand", "queenstown"),
                ("singapore", "singapore"),
            ):
                assert (
                    client.get(f"{COUNTRY}/{ids.country_id(country)}").status_code
                    == 200
                )
                assert (
                    client.get(f"{CITY}/{ids.city_id(country, city)}").status_code
                    == 200
                )

    def test_seeding_twice_does_not_duplicate(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'seeded.db'}"
        totals = []
        for _ in range(2):
            with TestClient(create_app(Settings(database_url=url))) as client:
                totals.append(client.request("QUERY", COUNTRY, json={}).json()["total"])
        assert totals[0] == totals[1]
