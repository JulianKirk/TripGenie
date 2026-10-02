"""The knowledge box: the shared RAG server is a MockTransport here.

Every outcome is a 200 with a `status`, so what is worth asserting is which
status each RAG answer (or failure) becomes, and that the question goes out
scoped to student-2.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import Settings

RAG_URL = "http://rag.test"
CITATION = {
    "source_id": "accommodation-pricing-and-costs",
    "path": "ai-services/rag-server/knowledge/accommodation/pricing-and-costs.md",
    "title": "Accommodation Pricing and Trip Costs",
    "section": "Accommodation costs: the cost of one stay",
    "chunk_id": "accommodation-pricing-and-costs:3",
    "excerpt": "The cost of a stay is the price per night multiplied by...",
}


def rag_answer(**overrides):
    data = {
        "schema_version": "1",
        "run_id": "rag-run-1",
        "correlation_id": "c",
        "answer": "Price per night times the number of nights.",
        "confidence_category": "high",
        "insufficient_context": False,
        "citations": [CITATION],
        "retrieval": {"requested_top_k": 5, "returned_chunks": 3, "maximum_score": 0.9},
    } | overrides
    return httpx.Response(200, json={"data": data})


def ask(handler, *, rag_url=RAG_URL, question="How is a stay priced?"):
    sent = []

    def recording(request):
        sent.append(json.loads(request.content))
        return handler(request)

    app = create_app(
        Settings(rag_url=rag_url),
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
        rag_transport=httpx.MockTransport(recording),
    )
    with TestClient(app) as client:
        response = client.post("/accommodation/knowledge", json={"question": question})
    return response, sent


def test_a_grounded_answer_carries_citations_and_confidence():
    response, sent = ask(lambda _: rag_answer())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["confidence_category"] == "high"
    assert body["citations"][0]["source_id"] == "accommodation-pricing-and-costs"
    assert sent[0]["feature"] == "student-2"
    assert sent[0]["query"] == "How is a stay priced?"


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "insufficient_context": True,
            "confidence_category": "insufficient_context",
            "citations": [],
        },
        # No citations is the server abstaining, whatever else it says.
        {"citations": []},
    ],
)
def test_no_grounding_is_insufficient_context(overrides):
    body = ask(lambda _: rag_answer(**overrides))[0].json()
    assert body["status"] == "insufficient_context"
    assert body["confidence_category"] == "insufficient_context"
    assert body["citations"] == []


def test_unset_rag_url_is_disabled_and_sends_nothing():
    response, sent = ask(lambda _: rag_answer(), rag_url=None)
    assert response.json()["status"] == "disabled"
    assert sent == []


@pytest.mark.parametrize(
    ("upstream", "message"),
    [
        (httpx.Response(503, json={"error": {"code": "INDEX_NOT_READY"}}), "not ready"),
        (
            httpx.Response(504, json={"error": {"code": "DEPENDENCY_TIMEOUT"}}),
            "timed out",
        ),
        (httpx.Response(400, json={"error": {"code": "VALIDATION_ERROR"}}), "accept"),
        (httpx.Response(200, json={"data": {"answer": "no schema"}}), "malformed"),
        (httpx.Response(500, text="boom"), "failed to answer"),
    ],
)
def test_upstream_failures_are_an_error_status(upstream, message):
    body = ask(lambda _: upstream)[0].json()
    assert body["status"] == "error"
    assert message in body["error"]


def test_an_unreachable_rag_server_is_an_error_status():
    def down(request):
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    body = ask(down)[0].json()
    assert body["status"] == "error"
    assert "unavailable" in body["error"]


def test_a_blank_question_is_rejected():
    response, sent = ask(lambda _: rag_answer(), question="   ")
    # This service reports request validation as 400; see errors.py.
    assert response.status_code == 400
    assert sent == []


def test_rag_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("RAG_URL", "")
    monkeypatch.setenv("RAG_TIMEOUT", "12.5")
    settings = Settings.from_env()
    # Declared-but-empty is the ordinary way to switch it off, as CI does.
    assert settings.rag_url is None
    assert settings.rag_timeout == 12.5
    monkeypatch.setenv("RAG_URL", "http://host.docker.internal:8011")
    assert Settings.from_env().rag_url == "http://host.docker.internal:8011"
