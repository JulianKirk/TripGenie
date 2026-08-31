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


class FakeBackend:
    """Records the last QUERY body so a test can assert on what was sent, and
    answers with whatever `response` is set to."""

    def __init__(self):
        self.body = None
        self.response = httpx.Response(
            200, json={"accommodations": [LISTING], "total": 1}
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "QUERY":
            self.body = json.loads(request.content)
        if request.url.path.startswith("/accommodation/"):
            return httpx.Response(200, json=DETAIL)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return self.response


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
