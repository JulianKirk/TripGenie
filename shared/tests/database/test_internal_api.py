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
CURRENCY = "/internal/currency"


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


class TestCreateCurrency:
    def test_returns_201_and_the_derived_id(self, client, australia):
        response = client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        )
        assert response.status_code == 201
        assert response.json() == {
            "id": str(ids.currency_id("australia", "australian dollar")),
            "name": "australian dollar",
            "code": "AUD",
            "symbol": "$",
            "conversion_rate": 1.0,
            "country_id": australia["id"],
        }

    def test_creating_the_same_currency_twice_returns_200(self, client, australia):
        payload = {
            "name": "australian dollar",
            "code": "AUD",
            "symbol": "$",
            "conversion_rate": 1.0,
            "country_id": australia["id"],
        }
        client.post(CURRENCY, json=payload)
        assert client.post(CURRENCY, json=payload).status_code == 200

    def test_a_second_currency_for_one_country_is_409(self, client, australia):
        """The one-to-one is a UNIQUE constraint underneath -- without the
        check in the router it would surface as a 500 out of SQLite."""
        client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        )
        response = client.post(
            CURRENCY,
            json={
                "name": "bitcoin",
                "code": "XBT",
                "symbol": "B",
                "conversion_rate": 0.00002,
                "country_id": australia["id"],
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "country already has a currency"

    def test_the_same_currency_under_two_countries_is_allowed(self, client):
        """France and Italy both spend euros. Under the one-to-one rule that is
        two rows, not a conflict."""
        for name in ("france", "italy"):
            country = client.post(COUNTRY, json={"name": name}).json()
            response = client.post(
                CURRENCY,
                json={
                    "name": "euro",
                    "code": "EUR",
                    "symbol": "\u20ac",
                    "conversion_rate": 0.57,
                    "country_id": country["id"],
                },
            )
            assert response.status_code == 201

    def test_unknown_country_is_404(self, client):
        response = client.post(
            CURRENCY,
            json={
                "name": "x",
                "code": "XXX",
                "symbol": "x",
                "conversion_rate": 1.0,
                "country_id": str(uuid4()),
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "country not found"

    def test_a_currency_without_a_symbol_is_400(self, client, australia):
        response = client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AUD",
                "country_id": australia["id"],
            },
        )
        assert response.status_code == 400

    def test_a_rate_of_zero_or_less_is_400(self, client, australia):
        """A zero or negative rate is not a cheap currency, it is a broken
        row -- and one that would divide badly downstream."""
        for rate in (0, -1.5):
            response = client.post(
                CURRENCY,
                json={
                    "name": "australian dollar",
                    "code": "AUD",
                    "symbol": "$",
                    "conversion_rate": rate,
                    "country_id": australia["id"],
                },
            )
            assert response.status_code == 400

    def test_a_currency_without_a_rate_is_400(self, client, australia):
        response = client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "country_id": australia["id"],
            },
        )
        assert response.status_code == 400

    def test_a_code_that_is_not_three_characters_is_400(self, client, australia):
        response = client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AU",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        )
        assert response.status_code == 400


class TestGetCurrency:
    def test_returns_the_row(self, client, australia):
        created = client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        ).json()
        assert client.get(f"{CURRENCY}/{created['id']}").json() == created

    def test_missing_is_404(self, client):
        assert client.get(f"{CURRENCY}/{uuid4()}").status_code == 404


class TestQueryCurrency:
    def test_filters_by_country(self, client, australia):
        japan = client.post(COUNTRY, json={"name": "japan"}).json()
        client.post(
            CURRENCY,
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        )
        client.post(
            CURRENCY,
            json={
                "name": "japanese yen",
                "code": "JPY",
                "symbol": "\u00a5",
                "conversion_rate": 98.0,
                "country_id": japan["id"],
            },
        )
        body = client.request(
            "QUERY", CURRENCY, json={"currency": {"country_id": japan["id"]}}
        ).json()
        assert [row["name"] for row in body["currencies"]] == ["japanese yen"]
        assert body["total"] == 1

    def test_code_matches_every_country_that_spends_it(self, client):
        """EUR is not one row. Asking by code is asking "who spends this"."""
        for name in ("france", "italy"):
            country = client.post(COUNTRY, json={"name": name}).json()
            client.post(
                CURRENCY,
                json={
                    "name": "euro",
                    "code": "EUR",
                    "symbol": "\u20ac",
                    "conversion_rate": 0.57,
                    "country_id": country["id"],
                },
            )
        body = client.request(
            "QUERY", CURRENCY, json={"currency": {"code": "eur"}}
        ).json()
        assert body["total"] == 2

    def test_unknown_field_is_400(self, client):
        response = client.request("QUERY", CURRENCY, json={"currency": {"iso": "AUD"}})
        assert response.status_code == 400


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
