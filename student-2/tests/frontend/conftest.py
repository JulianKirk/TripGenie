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
    {"itinerary_id": "trip_sydney", "name": "Sydney Getaway", "selected": False},
    {"itinerary_id": "trip_tokyo", "name": "Tokyo City Break", "selected": True},
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
        self.itinerary_response: httpx.Response | None = None
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
        if request.url.path.startswith("/accommodation/"):
            return httpx.Response(200, json=DETAIL)
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

    def _itineraries(self, request: httpx.Request) -> httpx.Response:
        """The real backend answers PUT and DELETE with the whole list, so the
        fake toggles its own state and does the same."""
        self.itinerary_calls.append((request.method, request.url.path))
        if self.itinerary_response is not None:
            return self.itinerary_response

        itinerary_id = request.url.path.rsplit("/", 1)[-1]
        for itinerary in self.itineraries:
            if itinerary["itinerary_id"] == itinerary_id:
                if request.method == "PUT":
                    itinerary["selected"] = True
                elif request.method == "DELETE":
                    itinerary["selected"] = False

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
