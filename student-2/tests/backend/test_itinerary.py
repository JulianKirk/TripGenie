"""The itinerary integration -- this service calling student 1's.

Student 1 is a `MockTransport` here for the same reason the database service is
in test_backend.py: the interesting cases are its failures and its envelope, not
its storage. What this service owns is the merge -- turning "every itinerary"
plus "the ones holding this accommodation" into the ticked/unticked list the
picker draws.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.client import BAD_RESPONSE
from backend_service.config import (
    DEFAULT_ITINERARY_PREFIX,
    DEFAULT_ITINERARY_URL,
    Settings,
)
from backend_service.itinerary_client import UNAVAILABLE, ItineraryClient

ITINERARY_URL = "http://itinerary.test"
NO_ROUTE = "no route to student 1"
ACCOMMODATION_ID = "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
PICKER = f"/accommodation/{ACCOMMODATION_ID}/itineraries"

SYDNEY = {
    "id": "trip_sydney",
    "name": "Sydney Getaway",
    "destination": "Sydney",
    "start_date": "2027-04-01",
    "end_date": "2027-04-03",
    "traveller_count": 2,
    "status": "planned",
}
TOKYO = {**SYDNEY, "id": "trip_tokyo", "name": "Tokyo City Break"}


class FakeItineraryApi:
    """Student 1's public API, envelopes and all."""

    def __init__(self):
        self.trips = [SYDNEY, TOKYO]
        self.holding: set[str] = set()
        # (method, trip_id, body) -- the body matters now that a PUT carries
        # the stay the user picked.
        self.writes: list[tuple[str, str, dict | None]] = []
        # trip_id -> the pinned row, as student 1 stores it.
        self.stays: dict[str, dict] = {}
        self.stays_response: httpx.Response | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/trips":
            return httpx.Response(200, json={"data": self.trips})
        if path.endswith("/trips"):
            held = [trip for trip in self.trips if trip["id"] in self.holding]
            return httpx.Response(200, json={"data": held})

        trip_id = path.split("/trips/")[1].split("/")[0]

        if path.endswith("/accommodations") and request.method == "GET":
            if self.stays_response is not None:
                return self.stays_response
            row = self.stays.get(trip_id)
            return httpx.Response(200, json={"data": [row] if row else []})

        body = json.loads(request.content) if request.content else None
        self.writes.append((request.method, trip_id, body))
        if request.method == "PUT":
            self.holding.add(trip_id)
            self.stays[trip_id] = {
                "trip_id": trip_id,
                "accommodation_id": ACCOMMODATION_ID,
                "date": (body or {}).get("date") or "2027-04-01",
                "check_in_time": (body or {}).get("check_in_time"),
                "check_out": (body or {}).get("check_out"),
                "check_out_time": (body or {}).get("check_out_time"),
            }
            return httpx.Response(200, json={"data": self.stays[trip_id]})
        if trip_id not in self.holding:
            return httpx.Response(
                404, json={"error": {"code": "NOT_FOUND", "message": "nope"}}
            )
        self.holding.discard(trip_id)
        self.stays.pop(trip_id, None)
        return httpx.Response(200, json={"data": {"id": trip_id, "deleted": True}})


@pytest.fixture
def itinerary_api():
    return FakeItineraryApi()


@pytest.fixture
def client(itinerary_api):
    app = create_app(
        Settings(itinerary_url=ITINERARY_URL),
        itinerary_transport=httpx.MockTransport(itinerary_api.handle),
    )
    with TestClient(app) as test_client:
        yield test_client


def call(handler, coroutine):
    """One `ItineraryClient` call against a handler -- the same shape as the
    `call` helper in test_backend.py."""
    client = ItineraryClient(
        Settings(itinerary_url=ITINERARY_URL),
        transport=httpx.MockTransport(handler),
    )

    async def once():
        try:
            return await coroutine(client)
        finally:
            await client.aclose()

    return asyncio.run(once())


class TestSettings:
    def test_defaults_point_at_student_ones_compose_service(self):
        settings = Settings()
        assert settings.itinerary_url == DEFAULT_ITINERARY_URL
        assert settings.itinerary_prefix == DEFAULT_ITINERARY_PREFIX

    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("ITINERARY_URL", ITINERARY_URL)
        monkeypatch.setenv("ITINERARY_TIMEOUT", "0.5")
        settings = Settings.from_env()
        assert settings.itinerary_url == ITINERARY_URL
        assert settings.itinerary_timeout == 0.5


class TestItineraryClient:
    def test_the_data_envelope_is_unwrapped(self):
        trips = call(
            lambda _: httpx.Response(200, json={"data": [SYDNEY]}),
            lambda client: client.list_itineraries(),
        )
        assert trips == [SYDNEY]

    def test_the_prefix_is_applied_once(self):
        seen = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={"data": []})

        call(handler, lambda client: client.list_itineraries())
        assert seen == ["/api/trips"]

    def test_an_unreachable_itinerary_service_is_a_503(self):
        def handler(request):
            raise httpx.ConnectError(NO_ROUTE)

        with pytest.raises(HTTPException) as raised:
            call(handler, lambda client: client.list_itineraries())

        assert raised.value.status_code == 503
        assert raised.value.detail == UNAVAILABLE

    def test_a_500_from_the_itinerary_service_is_a_502(self):
        with pytest.raises(HTTPException) as raised:
            call(
                lambda _: httpx.Response(500),
                lambda client: client.list_itineraries(),
            )

        assert raised.value.status_code == 502
        assert raised.value.detail == BAD_RESPONSE

    def test_a_404_is_relayed_unchanged(self):
        """Student 1 answering correctly about a missing trip is not this
        service failing, so the status survives the hop."""
        with pytest.raises(HTTPException) as raised:
            call(
                lambda _: httpx.Response(404, json={"detail": "no such trip"}),
                lambda client: client.remove(ACCOMMODATION_ID, "trip_missing"),
            )

        assert raised.value.status_code == 404


class TestPicker:
    def test_every_itinerary_is_listed_and_none_are_ticked_initially(self, client):
        body = client.get(PICKER).json()

        assert body["itineraries"] == [
            {
                "itinerary_id": "trip_sydney",
                "name": "Sydney Getaway",
                "selected": False,
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
                "check_in": None,
                "check_in_time": None,
                "check_out": None,
                "check_out_time": None,
            },
            {
                "itinerary_id": "trip_tokyo",
                "name": "Tokyo City Break",
                "selected": False,
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
                "check_in": None,
                "check_in_time": None,
                "check_out": None,
                "check_out_time": None,
            },
        ]

    def test_adding_ticks_only_that_itinerary(self, client, itinerary_api):
        body = client.put(f"{PICKER}/trip_tokyo").json()

        assert itinerary_api.writes == [
            (
                "PUT",
                "trip_tokyo",
                {
                    "date": None,
                    "check_in_time": None,
                    "check_out": None,
                    "check_out_time": None,
                },
            ),
        ]
        assert [it["selected"] for it in body["itineraries"]] == [False, True]

    def test_a_chosen_stay_reaches_student_1(self, client, itinerary_api):
        """The whole point of the panel: the dates the user picked are what
        gets stored, under the name student 1 gives them."""
        client.put(
            f"{PICKER}/trip_tokyo",
            json={
                "check_in": "2027-04-02",
                "check_in_time": "15:00",
                "check_out": "2027-04-03",
                "check_out_time": "10:00",
            },
        )

        assert itinerary_api.writes == [
            (
                "PUT",
                "trip_tokyo",
                {
                    "date": "2027-04-02",
                    "check_in_time": "15:00",
                    "check_out": "2027-04-03",
                    "check_out_time": "10:00",
                },
            ),
        ]

    def test_a_ticked_itinerary_carries_its_stay(self, client):
        client.put(
            f"{PICKER}/trip_tokyo",
            json={"check_in": "2027-04-02", "check_out": "2027-04-03"},
        )

        body = client.get(PICKER).json()
        tokyo = next(
            it for it in body["itineraries"] if it["itinerary_id"] == "trip_tokyo"
        )
        sydney = next(
            it for it in body["itineraries"] if it["itinerary_id"] == "trip_sydney"
        )

        assert (tokyo["check_in"], tokyo["check_out"]) == ("2027-04-02", "2027-04-03")
        # Not ticked, so there is no stay to report.
        assert (sydney["check_in"], sydney["check_out"]) == (None, None)

    def test_a_failing_stay_lookup_still_returns_the_ticks(self, client, itinerary_api):
        """The tick is the picker's job and the dates are a bonus, so losing
        the bonus must not cost the list."""
        client.put(f"{PICKER}/trip_tokyo")
        itinerary_api.stays_response = httpx.Response(500, json={})

        body = client.get(PICKER).json()

        assert [it["selected"] for it in body["itineraries"]] == [False, True]
        assert all(it["check_in"] is None for it in body["itineraries"])

    def test_an_accommodation_can_sit_on_several_itineraries(self, client):
        client.put(f"{PICKER}/trip_sydney")
        body = client.put(f"{PICKER}/trip_tokyo").json()

        assert [it["selected"] for it in body["itineraries"]] == [True, True]

    def test_adding_twice_is_not_a_conflict(self, client):
        first = client.put(f"{PICKER}/trip_tokyo")
        second = client.put(f"{PICKER}/trip_tokyo")

        assert first.status_code == second.status_code == 200
        assert second.json()["itineraries"][1]["selected"] is True

    def test_removing_unticks_it(self, client, itinerary_api):
        client.put(f"{PICKER}/trip_tokyo")

        body = client.delete(f"{PICKER}/trip_tokyo").json()

        assert itinerary_api.writes[-1] == ("DELETE", "trip_tokyo", None)
        assert [it["selected"] for it in body["itineraries"]] == [False, False]

    def test_a_malformed_accommodation_id_never_reaches_student_one(
        self, client, itinerary_api
    ):
        response = client.get("/accommodation/not-a-uuid/itineraries")

        assert response.status_code == 404
        assert itinerary_api.writes == []
