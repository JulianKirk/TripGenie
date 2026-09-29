from __future__ import annotations

import json
import logging
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings

from .conftest import database_handler

QUESTION = "How is the remaining budget calculated?"
CITATION = {
    "source_id": "student-5-budget-rules",
    "path": "student-5/docs/budget-rules.md",
    "title": "Student 5 Budget and Expense Rules",
    "section": "Remaining budget",
    "chunk_id": "student-5-budget-rules:2:ab12cd",
    "excerpt": "remaining_budget = total_budget - committed_costs - actual_spending",
}
GROUNDED = {
    "schema_version": "1",
    "run_id": "rag_01",
    "correlation_id": "student5-rag-000000000000",
    "answer": "Remaining budget is total minus committed and actual spending.",
    "confidence_category": "high",
    "insufficient_context": False,
    "citations": [CITATION],
    "retrieval": {"requested_top_k": 5, "returned_chunks": 1, "maximum_score": 0.81},
}
INSUFFICIENT = GROUNDED | {
    "answer": "There is not enough indexed context to answer this question.",
    "confidence_category": "insufficient_context",
    "insufficient_context": True,
    "citations": [],
    "retrieval": {"requested_top_k": 5, "returned_chunks": 0, "maximum_score": None},
}


def rag_app(settings: Settings, handler, *, enabled: bool = True) -> TestClient:
    return TestClient(
        create_app(
            replace(settings, rag_enabled=enabled, rag_base_url="http://rag.test"),
            database_transport=httpx.MockTransport(database_handler),
            rag_transport=httpx.MockTransport(handler),
        )
    )


def answering(payload: dict, status_code: int = 200):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json=payload)

    return handler, requests


def ask(client: TestClient, question: str = QUESTION) -> httpx.Response:
    return client.post("/api/rag/query", json={"question": question})


def test_grounded_answer_sends_fixed_feature_and_top_k(settings: Settings) -> None:
    handler, requests = answering({"data": GROUNDED})
    with rag_app(settings, handler) as client:
        response = ask(client, f"  {QUESTION}  ")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["confidence_category"] == "high"
    assert data["citations"][0]["source_id"] == "student-5-budget-rules"
    assert data["retrieval"]["maximum_score"] == 0.81
    sent = json.loads(requests[0].content)
    assert requests[0].url.path == "/query"
    assert sent["query"] == QUESTION
    assert sent["feature"] == "student-5"
    assert sent["top_k"] == 5
    assert sent["correlation_id"].startswith("student5-rag-")
    assert len(sent["correlation_id"]) == len("student5-rag-") + 12


def test_insufficient_context_is_returned_without_citations(
    settings: Settings,
) -> None:
    handler, _ = answering({"data": INSUFFICIENT})
    with rag_app(settings, handler) as client:
        response = ask(client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["insufficient_context"] is True
    assert data["confidence_category"] == "insufficient_context"
    assert data["citations"] == []


def test_disabled_rag_makes_no_outbound_call(settings: Settings) -> None:
    handler, requests = answering({"data": GROUNDED})
    with rag_app(settings, handler, enabled=False) as client:
        response = ask(client)
        health = client.get("/health").json()["data"]

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RAG_DISABLED"
    assert requests == []
    assert health["integrations"]["rag"] == "disabled"


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_question_is_validated_before_rag(settings: Settings, question: str) -> None:
    handler, requests = answering({"data": GROUNDED})
    with rag_app(settings, handler) as client:
        response = client.post(
            "/api/rag/query",
            json={"question": question, "feature": "student-1"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert requests == []


def test_browser_cannot_choose_feature_or_top_k(settings: Settings) -> None:
    handler, requests = answering({"data": GROUNDED})
    with rag_app(settings, handler) as client:
        response = client.post(
            "/api/rag/query",
            json={"question": QUESTION, "feature": "student-1", "top_k": 10},
        )

    assert response.status_code == 422
    assert requests == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (httpx.ConnectError("refused"), 503, "DEPENDENCY_UNAVAILABLE"),
        (httpx.ReadTimeout("slow"), 504, "DEPENDENCY_TIMEOUT"),
    ],
)
def test_transport_failures_are_structured(
    settings: Settings, error: Exception, status_code: int, code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with rag_app(settings, handler) as client:
        response = ask(client)
        ready = client.get("/ready")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"][0]["field"] == "rag"
    assert ready.status_code == 200


@pytest.mark.parametrize(
    ("upstream_status", "upstream_code", "status_code", "code"),
    [
        (503, "INDEX_NOT_READY", 503, "INDEX_NOT_READY"),
        (503, "DEPENDENCY_UNAVAILABLE", 503, "DEPENDENCY_UNAVAILABLE"),
        (504, "DEPENDENCY_TIMEOUT", 504, "DEPENDENCY_TIMEOUT"),
        (502, "BAD_GATEWAY", 502, "INVALID_DEPENDENCY_RESPONSE"),
        (500, "INTERNAL", 502, "INVALID_DEPENDENCY_RESPONSE"),
        (422, "VALIDATION_ERROR", 502, "INVALID_DEPENDENCY_RESPONSE"),
    ],
)
def test_upstream_errors_are_mapped(
    settings: Settings,
    upstream_status: int,
    upstream_code: str,
    status_code: int,
    code: str,
) -> None:
    handler, _ = answering(
        {"error": {"code": upstream_code, "message": "secret upstream detail"}},
        upstream_status,
    )
    with rag_app(settings, handler) as client:
        response = ask(client)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "secret upstream detail" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"data": GROUNDED | {"schema_version": "2"}},
        {"data": GROUNDED | {"confidence_category": "certain"}},
        {"data": GROUNDED | {"citations": []}},
        {"data": INSUFFICIENT | {"citations": [CITATION]}},
        {"data": INSUFFICIENT | {"confidence_category": "low"}},
        {"data": {"answer": "missing fields"}},
        {"answer": "no envelope"},
    ],
)
def test_contract_violations_return_bad_gateway(
    settings: Settings, payload: dict
) -> None:
    handler, _ = answering(payload)
    with rag_app(settings, handler) as client:
        response = ask(client)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INVALID_DEPENDENCY_RESPONSE"


def test_malformed_json_returns_bad_gateway(settings: Settings) -> None:
    with rag_app(settings, lambda _: httpx.Response(200, text="not json")) as client:
        response = ask(client)

    assert response.status_code == 502


def test_logs_exclude_question_and_answer(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    handler, _ = answering({"data": GROUNDED})
    with caplog.at_level(logging.INFO), rag_app(settings, handler) as client:
        ask(client)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "student5-rag-" in messages
    assert "outcome=high" in messages
    assert QUESTION not in messages
    assert GROUNDED["answer"] not in messages
    assert CITATION["excerpt"] not in messages
