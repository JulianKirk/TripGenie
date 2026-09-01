"""Unit tests for the accommodation backend service -- the parts that need no
database service at all.

Everything here is either pure (settings, schemas, `parse`) or driven by a
`httpx.MockTransport`, which is how the failures a working database service
will not produce on demand get tested: a timeout, a 500, a body that is not
JSON. The cross-service behaviour lives in tests/e2e.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.client import BAD_RESPONSE, UNAVAILABLE, DatabaseClient, parse
from backend_service.config import DEFAULT_DATABASE_URL, DEFAULT_DB_TIMEOUT, Settings
from backend_service.schemas import Accommodation, AccommodationQueryRequest

DATABASE_URL = "http://database.test"
LOCATION_URL = "http://location.test"
NO_ROUTE = "no route to the database service"
TOO_SLOW = "slower than DB_TIMEOUT"


def no_places(request):
    """A shared reference service that knows of nowhere.

    Enough for the tests below: none of them assert on a place name, and the
    stub keeps a unit test from dialling a real socket when a response does
    carry a place. The real thing is in tests/e2e; the client itself is in
    tests/backend/test_location.py.
    """
    key = "countries" if "country" in str(request.url) else "cities"
    return httpx.Response(200, json={key: [], "total": 0})


@pytest.fixture
def mock_client():
    """Build a backend whose database service is the given handler."""

    def factory(handler, location=no_places):
        app = create_app(
            Settings(database_url=DATABASE_URL, location_url=LOCATION_URL),
            transport=httpx.MockTransport(handler),
            location_transport=httpx.MockTransport(location),
        )
        return TestClient(app)

    return factory


def call(handler, coroutine):
    """Run one `DatabaseClient` call against a handler.

    `asyncio.run` rather than an async test: the client is the only async thing
    in this service, and one helper is cheaper than an async test plugin.
    """
    client = DatabaseClient(
        Settings(database_url=DATABASE_URL), transport=httpx.MockTransport(handler)
    )

    async def once():
        try:
            return await coroutine(client)
        finally:
            await client.aclose()

    return asyncio.run(once())


class TestSettings:
    def test_defaults_point_at_the_compose_service(self):
        settings = Settings()
        assert settings.database_url == DEFAULT_DATABASE_URL
        assert settings.db_timeout == DEFAULT_DB_TIMEOUT

    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
        monkeypatch.setenv("DB_TIMEOUT", "0.5")
        settings = Settings.from_env()
        assert settings.database_url == DATABASE_URL
        assert settings.db_timeout == 0.5


class TestQueryRequest:
    """The search this service accepts, validated before a round trip."""

    def test_paging_defaults(self):
        query = AccommodationQueryRequest()
        assert (query.limit, query.offset) == (20, 0)

    @pytest.mark.parametrize(
        "body",
        [
            {"accommodation": {"location_details": {"city": "sydney"}}},
            {"room_count_minimum": 2},
            {"accommodation": {"contry": "australia"}},
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"price_min": -1},
            {"rating_max": 6},
        ],
    )
    def test_a_malformed_search_is_rejected_here(self, body):
        with pytest.raises(ValueError):
            AccommodationQueryRequest.model_validate(body)

    def test_a_city_with_its_country_is_fine(self):
        location = {"city": "sydney", "country": "australia"}
        query = AccommodationQueryRequest.model_validate(
            {"accommodation": {"location_details": location}}
        )
        assert query.accommodation.location_details.city == "sydney"

    def test_an_unset_bound_is_not_dumped(self):
        """What the QUERY route relies on: the database service forbids unknown
        fields but would accept an explicit null bound and filter on it."""
        body = AccommodationQueryRequest().model_dump(mode="json", exclude_none=True)
        assert body == {"accommodation": {}, "limit": 20, "offset": 0}


class TestParse:
    def test_a_documented_body_becomes_the_message(self):
        assert parse(Accommodation, {"name": "cabin"}).name == "cabin"

    @pytest.mark.parametrize(
        "body", [{"rows": []}, {"name": "cabin", "beds": 2}, "not an object"]
    )
    def test_drift_is_a_502(self, body):
        """This service declares the accommodation message separately from the
        database service, so a response that does not fit is a bad gateway."""
        with pytest.raises(HTTPException) as raised:
            parse(Accommodation, body)
        assert raised.value.status_code == 502
        assert raised.value.detail == BAD_RESPONSE


class TestDatabaseClient:
    def test_it_calls_the_documented_path(self):
        seen = []

        def record(request):
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={})

        call(record, lambda db: db.query({"limit": 20}))
        call(record, lambda db: db.get("11111111-1111-1111-1111-111111111111"))
        assert seen == [
            ("QUERY", "/internal/accommodation"),
            ("GET", "/internal/accommodation/11111111-1111-1111-1111-111111111111"),
        ]

    def test_it_returns_the_decoded_body(self):
        body = call(
            lambda _: httpx.Response(200, json={"total": 0, "accommodations": []}),
            lambda db: db.query({}),
        )
        assert body == {"total": 0, "accommodations": []}

    def test_the_databases_4xx_is_re_raised_unchanged(self):
        """A 4xx is the database service answering correctly about a bad
        request, so the caller sees the same status and detail."""
        with pytest.raises(HTTPException) as raised:
            call(
                lambda _: httpx.Response(
                    404, json={"detail": "accommodation not found"}
                ),
                lambda db: db.get("11111111-1111-1111-1111-111111111111"),
            )
        assert raised.value.status_code == 404
        assert raised.value.detail == "accommodation not found"

    def test_a_4xx_body_without_a_detail_is_kept_whole(self):
        with pytest.raises(HTTPException) as raised:
            call(lambda _: httpx.Response(400, json=["bad"]), lambda db: db.query({}))
        assert raised.value.detail == ["bad"]


class TestDatabaseFailures:
    """The statuses that originate here: the request was fine, the data was
    not reachable. Driven through the app, because the mapping is only useful
    if the routes actually surface it."""

    def test_a_timeout_is_503(self, mock_client):
        def slow(request):
            raise httpx.ReadTimeout(TOO_SLOW, request=request)

        with mock_client(slow) as client:
            response = client.get("/accommodation")
        assert response.status_code == 503
        assert response.json()["detail"] == UNAVAILABLE

    def test_a_database_500_is_502(self, mock_client):
        with mock_client(lambda _: httpx.Response(500, json={"detail": "boom"})) as c:
            response = c.get("/accommodation")
        assert response.status_code == 502
        assert response.json()["detail"] == BAD_RESPONSE

    def test_a_non_json_body_is_502(self, mock_client):
        with mock_client(lambda _: httpx.Response(200, text="<html>nope")) as client:
            response = client.get("/accommodation")
        assert response.status_code == 502

    def test_an_unexpected_shape_is_502(self, mock_client):
        with mock_client(lambda _: httpx.Response(200, json={"rows": []})) as client:
            response = client.get("/accommodation")
        assert response.status_code == 502


class TestHealthWithoutADatabase:
    def test_degraded_but_still_200_when_the_database_is_unreachable(self, mock_client):
        """The question this endpoint answers is whether *this* service is
        running, and it is -- so an unreachable database is a 200 that says
        so, not a 503."""

        def unreachable(request):
            raise httpx.ConnectError(NO_ROUTE, request=request)

        with mock_client(unreachable, location=unreachable) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "degraded",
            "service": "student-2-backend",
            "database": "unreachable",
            "location": "unreachable",
        }

    def test_a_health_body_that_says_nothing_is_not_read_as_ok(self, mock_client):
        with mock_client(lambda _: httpx.Response(200, json={})) as client:
            body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["database"] == "unreachable"
