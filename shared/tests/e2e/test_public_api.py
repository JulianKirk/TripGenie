"""End-to-end tests for the public shared reference API, driven through
TestClient against the real database service over ASGI. Covers the contract in
shared/docs/backend-service-api.md.

Rows are seeded through the database service's own POST -- this service has no
write path, by design.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from shared_database_service import ids


@pytest.fixture
def australia(database):
    return database.post(
        "/internal/location/country", json={"name": "australia"}
    ).json()


@pytest.fixture
def seeded(database, australia):
    japan = database.post("/internal/location/country", json={"name": "japan"}).json()
    for country, name in (
        (australia, "sydney"),
        (australia, "melbourne"),
        (japan, "tokyo"),
    ):
        database.post(
            "/internal/location/city", json={"name": name, "country_id": country["id"]}
        )
    return japan


class TestHealth:
    def test_reports_the_database_behind_it(self, client):
        assert client.get("/health").json() == {
            "status": "ok",
            "service": "shared-backend",
            "database": "ok",
        }


class TestCountry:
    def test_get_returns_the_row(self, client, australia):
        response = client.get(f"/location/country/{australia['id']}")
        assert response.status_code == 200
        assert response.json() == {
            "id": str(ids.country_id("australia")),
            "name": "australia",
        }

    def test_get_missing_is_404(self, client):
        assert client.get(f"/location/country/{uuid4()}").status_code == 404

    def test_list_returns_everything_paginated(self, client, seeded):
        body = client.get("/location/country").json()
        assert body["total"] == 2
        assert [row["name"] for row in body["countries"]] == ["australia", "japan"]

    def test_query_matches_a_substring(self, client, seeded):
        body = client.request(
            "QUERY", "/location/country", json={"country": {"name": "APAN"}}
        ).json()
        assert [row["name"] for row in body["countries"]] == ["japan"]

    def test_write_endpoints_are_not_exposed(self, client):
        # POST lives on the database service only -- see routers/location.py.
        assert (
            client.post("/location/country", json={"name": "narnia"}).status_code == 405
        )


class TestCity:
    def test_get_returns_the_row(self, client, seeded, australia):
        city_id = ids.city_id("australia", "sydney")
        assert client.get(f"/location/city/{city_id}").json() == {
            "id": str(city_id),
            "name": "sydney",
            "country_id": australia["id"],
        }

    def test_list_is_pageable(self, client, seeded):
        body = client.get("/location/city", params={"limit": 2, "offset": 0}).json()
        assert body["total"] == 3
        assert len(body["cities"]) == 2

    def test_query_filters_by_country(self, client, seeded):
        body = client.request(
            "QUERY", "/location/city", json={"city": {"country_id": seeded["id"]}}
        ).json()
        assert [row["name"] for row in body["cities"]] == ["tokyo"]

    def test_an_unknown_field_is_400(self, client):
        response = client.request("QUERY", "/location/city", json={"city": {"nope": 1}})
        assert response.status_code == 400


class TestCurrency:
    @pytest.fixture
    def aud(self, database, australia):
        return database.post(
            "/internal/currency",
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        ).json()

    def test_get_returns_the_row(self, client, aud, australia):
        assert client.get(f"/currency/{aud['id']}").json() == {
            "id": str(ids.currency_id("australia", "australian dollar")),
            "name": "australian dollar",
            "code": "AUD",
            "symbol": "$",
            "conversion_rate": 1.0,
            "country_id": australia["id"],
        }

    def test_get_missing_is_404(self, client):
        assert client.get(f"/currency/{uuid4()}").status_code == 404

    def test_list_returns_everything(self, client, aud):
        body = client.get("/currency").json()
        assert body["total"] == 1
        assert body["currencies"][0]["symbol"] == "$"

    def test_query_filters_by_country(self, client, aud, australia):
        body = client.request(
            "QUERY", "/currency", json={"currency": {"country_id": australia["id"]}}
        ).json()
        assert [row["name"] for row in body["currencies"]] == ["australian dollar"]

    def test_the_rate_survives_both_hops(self, client, aud):
        """The rate is a float through two JSON round trips -- the kind of
        field that quietly turns into a string somewhere."""
        body = client.get(f"/currency/{aud['id']}").json()
        assert body["conversion_rate"] == 1.0
        assert isinstance(body["conversion_rate"], float)

    def test_query_matches_a_code(self, client, aud):
        body = client.request(
            "QUERY", "/currency", json={"currency": {"code": "AUD"}}
        ).json()
        assert [row["name"] for row in body["currencies"]] == ["australian dollar"]

    def test_write_endpoints_are_not_exposed(self, client, australia):
        assert (
            client.post(
                "/currency",
                json={
                    "name": "bitcoin",
                    "code": "XBT",
                    "symbol": "B",
                    "conversion_rate": 0.00002,
                    "country_id": australia["id"],
                },
            ).status_code
            == 405
        )


class TestCurrencyForCountry:
    """The shortcut endpoint: a country name in, its currency out.

    Two calls to the database service behind one request, so this is the route
    most worth driving end to end rather than against a stub.
    """

    @pytest.fixture
    def aud(self, database, australia):
        return database.post(
            "/internal/currency",
            json={
                "name": "australian dollar",
                "code": "AUD",
                "symbol": "$",
                "conversion_rate": 1.0,
                "country_id": australia["id"],
            },
        ).json()

    def test_returns_the_countrys_currency(self, client, aud):
        assert (
            client.get("/currency/country", params={"name": "australia"}).json() == aud
        )

    def test_the_name_is_exact_not_a_substring(self, client, aud):
        """The country search matches names as substrings; this endpoint must
        not, or `?name=a` would answer with whatever it happened to find."""
        response = client.get("/currency/country", params={"name": "austral"})
        assert response.status_code == 404
        assert response.json()["detail"] == "country not found"

    def test_the_name_ignores_case_and_padding(self, client, aud):
        assert (
            client.get("/currency/country", params={"name": "  Australia "}).json()
            == aud
        )

    def test_an_unknown_country_is_404(self, client, aud):
        response = client.get("/currency/country", params={"name": "narnia"})
        assert response.status_code == 404
        assert response.json()["detail"] == "country not found"

    def test_a_country_with_no_currency_says_so(self, client, database, aud):
        """A different answer to "no such country", and worth distinguishing --
        one is the caller's typo, the other is missing reference data."""
        database.post("/internal/location/country", json={"name": "narnia"})
        response = client.get("/currency/country", params={"name": "narnia"})
        assert response.status_code == 404
        assert response.json()["detail"] == "country has no currency"

    def test_a_missing_name_is_400(self, client):
        assert client.get("/currency/country").status_code == 400

    def test_a_shared_code_is_a_query_not_this_endpoint(self, client, database):
        """EUR is two rows. This endpoint answers with one currency, so the
        code look-up lives on QUERY /currency, where a list is the answer."""
        for name in ("france", "italy"):
            country = database.post(
                "/internal/location/country", json={"name": name}
            ).json()
            database.post(
                "/internal/currency",
                json={
                    "name": "euro",
                    "code": "EUR",
                    "symbol": "\u20ac",
                    "conversion_rate": 0.57,
                    "country_id": country["id"],
                },
            )
        body = client.request(
            "QUERY", "/currency", json={"currency": {"code": "EUR"}}
        ).json()
        assert body["total"] == 2
