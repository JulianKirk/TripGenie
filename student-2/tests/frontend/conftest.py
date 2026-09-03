"""Fixtures for the accommodation frontend tests.

The backend is a `MockTransport` rather than the real service: what these tests
are about is the translation in both directions -- form parameters into the
QUERY body the backend documents, and the JSON back into HTML. The real
backend/database pair is already exercised in tests/e2e.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from frontend_service.app import create_app
from frontend_service.config import Settings

LISTING = {
    "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
    "name": "Harbour View Hotel",
    "type": "hotel",
    "price_per_night": 320.0,
    "availability_status": "available",
    "rating": 4.6,
    "location_details": {"country": "australia", "city": "sydney"},
}
DETAIL = {
    **LISTING,
    "description": "Rooms over Circular Quay.",
    "amenities": ["wifi", "pool"],
    "location_details": {
        "country": "australia",
        "city": "sydney",
        "street": "george street",
        "street_number": 12,
    },
    "room_details": {
        "room_count": 1,
        "bed_count": 1,
        "bed_types": ["king"],
        "description": "King room.",
    },
}


ITINERARIES = [
    {
        "itinerary_id": "trip_sydney",
        "name": "Sydney Getaway",
        "selected": False,
        "start_date": "2027-04-01",
        "end_date": "2027-04-05",
        "check_in": None,
        "check_in_time": None,
        "check_out": None,
        "check_out_time": None,
    },
    {
        "itinerary_id": "trip_tokyo",
        "name": "Tokyo City Break",
        "selected": True,
        "start_date": "2027-06-10",
        "end_date": "2027-06-14",
        "check_in": "2027-06-11",
        "check_in_time": "15:00",
        "check_out": "2027-06-13",
        "check_out_time": "10:00",
    },
    # A second unticked itinerary, with a different window from the first.
    # Without it, "the chosen trip" and "the first trip" are the same row and
    # the panel could ignore the choice without any test noticing.
    {
        "itinerary_id": "trip_perth",
        "name": "Perth Workcation",
        "selected": False,
        "start_date": "2027-08-18",
        "end_date": "2027-08-24",
        "check_in": None,
        "check_in_time": None,
        "check_out": None,
        "check_out_time": None,
    },
]


# What the backend's POST /accommodation/ai-search answers with: the rows, and
# the search the model produced for the question.
AI_QUERY_USED = {
    "accommodation": {"location_details": {"country": "japan"}},
    "price_max": 100.0,
    "rating_min": 4.0,
    "limit": 20,
    "offset": 0,
}
AI_REPLY = "Looking for well-rated places in Japan under 100 a night."


class FakeBackend:
    """Records the last QUERY body so a test can assert on what was sent, and
    answers with whatever `response` is set to."""

    def __init__(self):
        self.body = None
        self.ai_question: str | None = None
        self.ai_timeout: float | None = None
        self.ai_response: httpx.Response | None = None
        self.itineraries = [dict(itinerary) for itinerary in ITINERARIES]
        self.itinerary_calls: list[tuple[str, str]] = []
        self.itinerary_bodies: list[dict] = []
        self.response_detail = DETAIL
        # Every write the page made: (method, path, decoded body). One list, so
        # a test asserts on what was sent without caring which verb sent it.
        self.writes: list[tuple[str, str, dict]] = []
        # Fails only the write, so the form redraw behind an error still works.
        self.write_response: httpx.Response | None = None
        # Fails only the single-accommodation lookup, which is what a stale
        # deep link hits.
        self.detail_response: httpx.Response | None = None
        self.itinerary_response: httpx.Response | None = None
        # Fails only the write, so the re-read behind an error still answers --
        # which is the real shape of a rejected stay.
        self.itinerary_write_response: httpx.Response | None = None
        self.response = httpx.Response(
            200, json={"accommodations": [LISTING], "total": 1}
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ai-search"):
            return self._ai_search(request)
        if request.method == "QUERY":
            self.body = json.loads(request.content)
        if "/itineraries" in request.url.path:
            return self._itineraries(request)
        if request.method in {"POST", "PUT", "DELETE"}:
            return self._write(request)
        if request.url.path.startswith("/accommodation/"):
            if self.detail_response is not None:
                return self.detail_response
            return httpx.Response(200, json=self.response_detail)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return self.response

    def _ai_search(self, request: httpx.Request) -> httpx.Response:
        self.ai_question = json.loads(request.content)["query"]
        self.ai_timeout = request.extensions["timeout"]["read"]
        if self.ai_response is not None:
            return self.ai_response
        return httpx.Response(
            200,
            json={
                "query_used": AI_QUERY_USED,
                "reply": AI_REPLY,
                "accommodations": [LISTING],
                "total": 1,
            },
        )

    def _write(self, request: httpx.Request) -> httpx.Response:
        """Create, edit and delete. Answers the way the real backend does:
        201 with the id and name, 200 with the row, 204 with nothing."""
        body = json.loads(request.content) if request.content else {}
        self.writes.append((request.method, request.url.path, body))
        if self.write_response is not None:
            return self.write_response
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(201, json={"id": LISTING["id"], "name": body["name"]})
        return httpx.Response(200, json={**DETAIL, **body})

    def _itineraries(self, request: httpx.Request) -> httpx.Response:
        """The real backend answers PUT and DELETE with the whole list, so the
        fake toggles its own state and does the same."""
        self.itinerary_calls.append((request.method, request.url.path))
        if self.itinerary_response is not None:
            return self.itinerary_response
        if self.itinerary_write_response is not None and request.method != "GET":
            return self.itinerary_write_response

        itinerary_id = request.url.path.rsplit("/", 1)[-1]
        for itinerary in self.itineraries:
            if itinerary["itinerary_id"] == itinerary_id:
                if request.method == "PUT":
                    itinerary["selected"] = True
                    sent = json.loads(request.content) if request.content else {}
                    self.itinerary_bodies.append(sent)
                    itinerary["check_in"] = sent.get("check_in")
                    itinerary["check_in_time"] = sent.get("check_in_time")
                    itinerary["check_out"] = sent.get("check_out")
                    itinerary["check_out_time"] = sent.get("check_out_time")
                elif request.method == "DELETE":
                    itinerary["selected"] = False
                    itinerary["check_in"] = None
                    itinerary["check_in_time"] = None
                    itinerary["check_out"] = None
                    itinerary["check_out_time"] = None

        return httpx.Response(200, json={"itineraries": self.itineraries})


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def client(backend):
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    with TestClient(app) as client:
        yield client
