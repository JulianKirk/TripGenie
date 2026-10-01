from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import TRIP_ID, FakeBackend

KNOWLEDGE = ("POST", "/activity/knowledge")
GUIDE = "ai-services/rag-server/knowledge/activities/booking-and-pricing.md"


def answered() -> dict[str, Any]:
    return {
        "status": "answered",
        "request_id": "student4-rag-test",
        "answer": "<b>Per-person</b> prices scale with the party size.",
        "confidence_category": "medium",
        "citations": [
            {
                "source_id": "activities-booking-and-pricing",
                "path": GUIDE,
                "title": "Activity Booking and Pricing Guide",
                "section": "Activity pricing: per-person and flat-admission prices",
                "chunk_id": "activities-booking-and-pricing:1:abc123",
                "excerpt": "A per-person price is charged for every participant.",
            }
        ],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 3,
            "maximum_score": 0.7412,
        },
        "run_id": "rag_01",
        "error": None,
    }


def ask(
    backend: FakeBackend, data: dict[str, str], *, htmx: bool = True
) -> httpx.Response:
    with TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    ) as client:
        response: httpx.Response = client.post(
            "/suggestions/ask",
            data=data,
            headers={"HX-Request": "true"} if htmx else {},
        )
    return response


def test_panel_offers_mcp_and_rag_modes(backend: FakeBackend) -> None:
    with TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    ) as client:
        text = client.get("/").text

    assert 'name="mode" value="tools" checked' in text
    assert 'name="mode" value="knowledge"' in text
    assert "Activity tools (MCP)" in text
    assert "Activity guides (RAG)" in text
    assert "<strong>Maintains Release 0 functionality.</strong>" in text


def test_knowledge_mode_renders_grounded_answer_with_citations(
    backend: FakeBackend,
) -> None:
    backend.overrides[KNOWLEDGE] = httpx.Response(200, json=answered())

    response = ask(
        backend,
        {
            "mode": "knowledge",
            "question": " How are prices totalled? ",
            "trip_id": TRIP_ID,
        },
    )

    assert response.status_code == 200
    assert json.loads(backend.last_request.content) == {
        "question": "How are prices totalled?"
    }
    text = response.text
    assert "&lt;b&gt;Per-person&lt;/b&gt;" in text
    assert "Confidence: Medium" in text
    assert "Activity Booking and Pricing Guide" in text
    assert "per-person and flat-admission prices" in text
    assert "knowledge/activities/booking-and-pricing.md" in text
    assert "A per-person price is charged" in text
    assert "top score 0.74" in text
    assert "student4-rag-test" in text
    assert "Tools used" not in text
    assert all(r.url.path != "/activity/assistant" for r in backend.requests)


def test_insufficient_context_is_shown_without_sources(backend: FakeBackend) -> None:
    data = answered()
    data.update(
        status="insufficient_context",
        answer="There is not enough indexed context to answer this question.",
        confidence_category="insufficient_context",
        citations=[],
    )
    backend.overrides[KNOWLEDGE] = httpx.Response(200, json=data)

    text = ask(backend, {"mode": "knowledge", "question": "Best laptop?"}).text

    assert "Confidence: Insufficient context" in text
    assert "There is not enough indexed context" in text
    assert "Sources" not in text


@pytest.mark.parametrize(
    ("status", "heading"),
    [
        ("disabled", "Activity guides disabled"),
        ("error", "Activity guides could not answer"),
    ],
)
def test_disabled_and_failed_answers_keep_browsing_available(
    backend: FakeBackend, status: str, heading: str
) -> None:
    backend.overrides[KNOWLEDGE] = httpx.Response(
        200,
        json={
            "status": status,
            "request_id": "student4-rag-test",
            "error": "Safe backend message.",
        },
    )

    text = ask(backend, {"mode": "knowledge", "question": "Sun safety?"}).text

    assert heading in text
    assert "Safe backend message." in text
    assert ("Activity browsing and the catalogue remain available." in text) is (
        status == "error"
    )


def test_backend_outage_renders_safe_error(backend: FakeBackend) -> None:
    backend.overrides[KNOWLEDGE] = httpx.ConnectError("refused")

    text = ask(backend, {"mode": "knowledge", "question": "Sun safety?"}).text

    assert "Activity guides unavailable" in text
    assert "The activities service is unavailable." in text


def test_plain_knowledge_form_returns_full_page(backend: FakeBackend) -> None:
    backend.overrides[KNOWLEDGE] = httpx.Response(200, json=answered())

    text = ask(backend, {"mode": "knowledge", "question": "Prices?"}, htmx=False).text

    assert "<!DOCTYPE html>" in text
    assert "Activity Booking and Pricing Guide" in text
    assert 'id="activity-dialog"' in text


def test_missing_mode_keeps_mcp_assistant_default(backend: FakeBackend) -> None:
    backend.overrides[("POST", "/activity/assistant")] = httpx.Response(
        200,
        json={"status": "error", "request_id": "student4-agent-x", "error": "off"},
    )

    ask(backend, {"question": "Walks"})

    assert backend.last_request.url.path == "/activity/assistant"
