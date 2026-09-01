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
