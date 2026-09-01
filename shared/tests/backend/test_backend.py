"""Unit tests for the shared reference backend service -- the parts that need
no database service at all.

Everything here is either pure (settings, schemas, `parse`) or driven by a
`httpx.MockTransport`, which is how the failures a working database service
will not produce on demand get tested: a timeout, a 500, a body that is not
JSON. The cross-service behaviour lives in tests/e2e.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from shared_backend_service.app import create_app
from shared_backend_service.client import (
    BAD_RESPONSE,
    UNAVAILABLE,
    DatabaseClient,
    parse,
)
from shared_backend_service.config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_DB_TIMEOUT,
    Settings,
)
from shared_backend_service.schemas import (
    Country,
    CountryQueryResponse,
    CurrencyQueryResponse,
)

DATABASE_URL = "http://database.test"
NO_ROUTE = "no route to the database service"
TOO_SLOW = "slower than DB_TIMEOUT"


@pytest.fixture
def mock_client():
    """Build a backend whose database service is the given handler."""

    def factory(handler):
        app = create_app(
            Settings(database_url=DATABASE_URL),
            transport=httpx.MockTransport(handler),
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
        assert settings.service_name == "shared-backend"

    def test_from_env_reads_the_documented_variables(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "http://elsewhere:1234")
        monkeypatch.setenv("DB_TIMEOUT", "0.5")
        settings = Settings.from_env()
        assert settings.database_url == "http://elsewhere:1234"
        assert settings.db_timeout == 0.5


class TestClientFailures:
    """The 502/503 mapping in ../../backend/shared_backend_service/client.py."""

    def test_no_route_is_503(self):
        def handler(request):
            raise httpx.ConnectError(NO_ROUTE, request=request)

        with pytest.raises(HTTPException) as caught:
            call(handler, lambda db: db.get("country", uuid4()))
        assert caught.value.status_code == 503
        assert caught.value.detail == UNAVAILABLE

    def test_timeout_is_503(self):
        def handler(request):
            raise httpx.ReadTimeout(TOO_SLOW, request=request)

        with pytest.raises(HTTPException) as caught:
            call(handler, lambda db: db.get("country", uuid4()))
        assert caught.value.status_code == 503

    def test_upstream_500_is_502(self):
        with pytest.raises(HTTPException) as caught:
            call(
                lambda _request: httpx.Response(500, json={"detail": "boom"}),
                lambda db: db.get("country", uuid4()),
            )
        assert caught.value.status_code == 502
        assert caught.value.detail == BAD_RESPONSE

    def test_body_that_is_not_json_is_502(self):
        with pytest.raises(HTTPException) as caught:
            call(
                lambda _request: httpx.Response(200, text="<html>nope</html>"),
                lambda db: db.get("country", uuid4()),
            )
        assert caught.value.status_code == 502

    def test_upstream_404_is_relayed_unchanged(self):
        """A 4xx is the database service answering correctly, so it reaches the
        caller as the same status and body."""
        with pytest.raises(HTTPException) as caught:
            call(
                lambda _request: httpx.Response(
                    404, json={"detail": "country not found"}
                ),
                lambda db: db.get("country", uuid4()),
            )
        assert caught.value.status_code == 404
        assert caught.value.detail == "country not found"


class TestParse:
    def test_a_response_that_does_not_fit_the_contract_is_502(self):
        with pytest.raises(HTTPException) as caught:
            parse(Country, {"id": "not-a-uuid"})
        assert caught.value.status_code == 502

    def test_an_unknown_field_from_the_database_service_is_502(self):
        # `extra="forbid"` is what makes drift loud instead of silent.
        with pytest.raises(HTTPException) as caught:
            parse(Country, {"name": "australia", "population": 27_000_000})
        assert caught.value.status_code == 502

    def test_a_matching_body_parses(self):
        parsed = parse(
            CountryQueryResponse, {"countries": [{"name": "australia"}], "total": 1}
        )
        assert parsed.total == 1


class TestRoutes:
    def test_health_reports_a_reachable_database(self, mock_client):
        client = mock_client(
            lambda _request: httpx.Response(200, json={"status": "ok", "service": "x"})
        )
        with client:
            assert client.get("/health").json() == {
                "status": "ok",
                "service": "shared-backend",
                "database": "ok",
            }

    def test_health_is_degraded_when_the_database_is_unreachable(self, mock_client):
        def handler(request):
            raise httpx.ConnectError(NO_ROUTE, request=request)

        client = mock_client(handler)
        with client:
            body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["database"] == "unreachable"

    def test_query_forwards_only_the_fields_the_caller_set(self, mock_client):
        """`exclude_none`: the database service forbids unknown fields but would
        happily filter on an explicit null."""
        sent = {}

        def handler(request):
            sent.update(json.loads(request.read()))
            return httpx.Response(200, json={"countries": [], "total": 0})

        client = mock_client(handler)
        with client:
            client.request(
                "QUERY", "/location/country", json={"country": {"name": "aus"}}
            )
        assert sent == {"country": {"name": "aus"}, "limit": 20, "offset": 0}

    def test_a_currency_query_forwards_only_what_was_set(self, mock_client):
        """Currency lives under its own prefix, not the location one -- a
        currency is not a place."""
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.read())
            return httpx.Response(200, json={"currencies": [], "total": 0})

        client = mock_client(handler)
        with client:
            client.request("QUERY", "/currency", json={"currency": {"symbol": "$"}})
        assert seen["path"] == "/internal/currency"
        assert seen["body"] == {"currency": {"symbol": "$"}, "limit": 20, "offset": 0}

    def test_a_currency_response_that_does_not_fit_the_contract_is_502(self):
        with pytest.raises(HTTPException) as caught:
            parse(CurrencyQueryResponse, {"currencies": [{"iso": "AUD"}], "total": 1})
        assert caught.value.status_code == 502

    def test_an_unknown_query_field_is_400_without_a_round_trip(self, mock_client):
        def handler(request):  # pragma: no cover - must never be reached
            unexpected = "the database service should not be called"
            raise AssertionError(unexpected)

        client = mock_client(handler)
        with client:
            assert (
                client.request(
                    "QUERY", "/location/country", json={"nope": 1}
                ).status_code
                == 400
            )
