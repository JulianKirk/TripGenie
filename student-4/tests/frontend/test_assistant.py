from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, DETAIL, FakeBackend


def result() -> dict[str, Any]:
    return {
        "status": "complete",
        "request_id": "student4-agent-test",
        "error": None,
        "parts": [
            {"type": "text", "text": "<script>alert(1)</script>"},
            {"type": "activity", "activity_id": ACTIVITY_ID},
        ],
        "activities": {ACTIVITY_ID: DETAIL},
        "unavailable_activity_ids": [],
        "tools": [
            {
                "tool": "activities_search",
                "arguments": {"text": "walk"},
                "status": "success",
                "duration_ms": 12,
                "correlation_id": "mcp-test",
                "activity_ids": [ACTIVITY_ID],
                "result_count": 1,
                "error": None,
            }
        ],
        "model": "test",
        "provider": "ollama",
    }


def test_assistant_renders_safe_cards_and_actual_trace(backend: FakeBackend) -> None:
    backend.overrides[("POST", "/activity/assistant")] = httpx.Response(
        200, json=result()
    )
    with TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    ) as client:
        response = client.post(
            "/suggestions/ask",
            data={"question": "Walks"},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text
    assert "<script>alert" not in response.text
    assert "Sydney Harbour guided walk" in response.text
    assert f"/activity/{ACTIVITY_ID}/itineraries/dialog" in response.text
    assert "Tools used" in response.text
    assert "activities_search" in response.text
    assert "mcp-test" in response.text
    assert "student4-agent-test" in response.text
    assert "/manage/" not in response.text
    assert backend.last_request.url.path == "/activity/assistant"


def test_plain_form_returns_full_page(backend: FakeBackend) -> None:
    backend.overrides[("POST", "/activity/assistant")] = httpx.Response(
        200, json=result()
    )
    with TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    ) as client:
        response = client.post("/suggestions/ask", data={"question": "Walks"})
    assert "<!DOCTYPE html>" in response.text
    assert 'id="activity-dialog"' in response.text


def test_error_preserves_execution_trace(backend: FakeBackend) -> None:
    data = result()
    data.update(status="error", parts=[], activities={}, error="MCP unavailable")
    data["tools"][0].update(status="error", error="PROVIDER_TIMEOUT")
    backend.overrides[("POST", "/activity/assistant")] = httpx.Response(200, json=data)
    with TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    ) as client:
        response = client.post(
            "/suggestions/ask",
            data={"question": "Walks"},
            headers={"HX-Request": "true"},
        )
    assert "MCP unavailable" in response.text
    assert "PROVIDER_TIMEOUT" in response.text
    assert "activities_search" in response.text
