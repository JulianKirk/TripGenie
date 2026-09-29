from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import TRIP_ID, FakeBackend


def frontend(backend: FakeBackend) -> TestClient:
    return TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    )


def test_index_offers_prompt_trip_context_and_immediate_progress(
    backend: FakeBackend,
) -> None:
    backend.overrides[("GET", "/activity/trips")] = httpx.Response(
        200,
        json={
            "available": True,
            "trips": [
                {
                    "id": TRIP_ID,
                    "name": "Sydney Getaway",
                    "destination": "Sydney",
                    "start_date": "2027-04-01",
                    "end_date": "2027-04-03",
                    "traveller_count": 2,
                    "status": "planned",
                    "notes": "Prefer a relaxed first day.",
                }
            ],
        },
    )

    text = frontend(backend).get("/").text

    assert "AI activity assistant" in text
    assert 'name="question"' in text
    assert 'name="trip_id"' in text
    assert "Sydney Getaway" in text
    assert "Understanding your request" in text
    assert "perform actions you request" in text
    assert "read-only MCP tools" not in text


def test_old_ai_form_routes_are_removed(backend: FakeBackend) -> None:
    with frontend(backend) as client:
        assert client.post("/suggestions/plan", data={}).status_code == 404
        assert client.post("/suggestions/evaluate", data={}).status_code == 404
