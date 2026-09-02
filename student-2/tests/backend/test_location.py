"""Unit tests for the shared reference service client and the id/name swap it
exists to perform.

Driven by a `httpx.MockTransport` standing in for the shared backend, so the
cache, the refetch-on-miss and the paging are all observable -- the number of
requests the stub sees is the assertion. The real two-service chain is exercised
in tests/e2e.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import Settings
from backend_service.location_client import UNAVAILABLE, LocationClient

DATABASE_URL = "http://database.test"
LOCATION_URL = "http://location.test"
NO_ROUTE = "no route to the location service"

AUSTRALIA = {"id": str(uuid4()), "name": "australia"}
SYDNEY = {"id": str(uuid4()), "name": "sydney", "country_id": AUSTRALIA["id"]}
JAPAN = {"id": str(uuid4()), "name": "japan"}
TOKYO = {"id": str(uuid4()), "name": "tokyo", "country_id": JAPAN["id"]}


class Shared:
    """A stub shared reference service that counts what it is asked.

    `places` is mutable so a test can add a country *after* the client has
    cached the list -- that is what "refetched on a miss" has to survive.
    """

    def __init__(self, countries=(AUSTRALIA,), cities=(SYDNEY,)):
        self.countries = list(countries)
        self.cities = list(cities)
        self.requests: list[httpx.URL] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url)
        rows = self.countries if "country" in request.url.path else self.cities
        key = "countries" if "country" in request.url.path else "cities"
        params = request.url.params
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 20))
        page = rows[offset : offset + limit]
        return httpx.Response(200, json={key: page, "total": len(rows)})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def run(shared: Shared, work):
    """Run one piece of client work against a stub, closing the client after."""
    client = LocationClient(
        Settings(location_url=LOCATION_URL), transport=shared.transport
    )

    async def once():
        try:
            return await work(client)
        finally:
            await client.aclose()

    return asyncio.run(once())


@pytest.fixture
def backend():
    """A backend wired to a stub database service and a stub shared service."""

    def factory(shared, database):
        app = create_app(
            Settings(database_url=DATABASE_URL, location_url=LOCATION_URL),
            transport=httpx.MockTransport(database),
            location_transport=shared.transport,
        )
        return TestClient(app)

    return factory


class TestNameToId:
    def test_resolves_a_country(self):
        shared = Shared()
        assert run(shared, lambda c: c.ids("australia", None)) == (
            UUID(AUSTRALIA["id"]),
            None,
        )

    def test_resolves_a_city_within_its_country(self):
        shared = Shared()
        assert run(shared, lambda c: c.ids("australia", "sydney")) == (
            UUID(AUSTRALIA["id"]),
            UUID(SYDNEY["id"]),
        )

    def test_ignores_case_and_padding(self):
        """The shared service stores names normalised, so matching on anything
        else would make "Sydney" a different place to "sydney"."""
        shared = Shared()
        assert run(shared, lambda c: c.ids("  AUSTRALIA ", "Sydney")) == (
            UUID(AUSTRALIA["id"]),
            UUID(SYDNEY["id"]),
        )

    def test_no_country_named_is_no_filter(self):
        shared = Shared()
        assert run(shared, lambda c: c.ids(None, None)) == (None, None)
        assert shared.requests == []

    def test_an_unknown_country_is_none(self):
        assert run(Shared(), lambda c: c.ids("narnia", None)) is None

    def test_a_city_in_the_wrong_country_is_none(self):
        """Sydney is not in Japan, and a filter that says it is matches nothing
        rather than quietly dropping the city."""
        shared = Shared(countries=(AUSTRALIA, JAPAN), cities=(SYDNEY, TOKYO))
        assert run(shared, lambda c: c.ids("japan", "sydney")) is None


class TestCache:
    def test_the_lists_are_fetched_once(self):
        shared = Shared()

        async def twice(client):
            await client.ids("australia", "sydney")
            await client.ids("australia", None)

        run(shared, twice)
        # One page of countries, one page of cities, and nothing more.
        assert len(shared.requests) == 2

    def test_a_miss_refetches_once_and_finds_a_new_place(self):
        shared = Shared()

        async def then_added(client):
            assert await client.ids("japan", None) is None
            shared.countries.append(JAPAN)
            return await client.ids("japan", None)

        assert run(shared, then_added) == (UUID(JAPAN["id"]), None)

    def test_every_page_is_fetched(self):
        """The shared service caps a page at 100, so a longer list is more than
        one request and a client that stops at the first would lose places."""
        countries = [
            {"id": str(uuid4()), "name": f"country {index}"} for index in range(150)
        ]
        shared = Shared(countries=countries, cities=())
        assert run(shared, lambda c: c.ids("country 149", None)) == (
            UUID(countries[149]["id"]),
            None,
        )


class TestIdToName:
    def test_maps_ids_back(self):
        shared = Shared()
        names = run(
            shared, lambda c: c.names([UUID(AUSTRALIA["id"]), UUID(SYDNEY["id"])])
        )
        assert names == {
            UUID(AUSTRALIA["id"]): "australia",
            UUID(SYDNEY["id"]): "sydney",
        }

    def test_an_id_the_shared_service_does_not_know_is_left_out(self):
        """The row still exists and still returns -- it just cannot say where
        it is. Better than failing a whole page over one stale reference."""
        shared = Shared()
        assert run(shared, lambda c: c.names([uuid4()])) == {}

    def test_no_ids_costs_no_call(self):
        shared = Shared()
        assert run(shared, lambda c: c.names([])) == {}
        assert shared.requests == []


class TestFailures:
    def test_an_unreachable_shared_service_is_503(self):
        def unreachable(request):
            raise httpx.ConnectError(NO_ROUTE, request=request)

        shared = Shared()
        shared.handle = unreachable
        with pytest.raises(HTTPException) as caught:
            run(shared, lambda c: c.ids("australia", None))
        assert caught.value.status_code == 503
        assert caught.value.detail == UNAVAILABLE


class TestThroughTheRoutes:
    def test_a_filter_reaches_the_database_service_as_ids(self, backend):
        sent = {}

        def database(request):
            sent.update(json.loads(request.read()))
            return httpx.Response(200, json={"accommodations": [], "total": 0})

        with backend(Shared(), database) as client:
            client.request(
                "QUERY",
                "/accommodation",
                json={
                    "accommodation": {
                        "location_details": {"country": "australia", "city": "sydney"}
                    }
                },
            )
        assert sent["accommodation"]["location_details"] == {
            "country_id": AUSTRALIA["id"],
            "city_id": SYDNEY["id"],
        }

    def test_a_place_that_does_not_exist_is_an_empty_result_not_an_error(self, backend):
        def database(request):  # pragma: no cover - must never be reached
            unexpected = "the database service should not be asked about Narnia"
            raise AssertionError(unexpected)

        with backend(Shared(), database) as client:
            response = client.request(
                "QUERY",
                "/accommodation",
                json={"accommodation": {"location_details": {"country": "narnia"}}},
            )
        assert response.status_code == 200
        assert response.json() == {"accommodations": [], "total": 0}

    def test_a_response_comes_back_carrying_names(self, backend):
        row = {
            "id": str(uuid4()),
            "name": "Harbour View Hotel",
            "location_details": {
                "country_id": AUSTRALIA["id"],
                "city_id": SYDNEY["id"],
            },
        }

        def database(request):
            return httpx.Response(200, json={"accommodations": [row], "total": 1})

        with backend(Shared(), database) as client:
            body = client.get("/accommodation").json()
        assert body["accommodations"][0]["location_details"] == {
            "country": "australia",
            "city": "sydney",
        }
