from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

from tests.backend.test_activity_api import FakeDatabase, location_handler

CITATION: dict[str, Any] = {
    "source_id": "activities-booking-and-pricing",
    "path": "ai-services/rag-server/knowledge/activities/booking-and-pricing.md",
    "title": "Activity Booking and Pricing Guide",
    "section": "Activity pricing: per-person and flat-admission prices",
    "chunk_id": "activities-booking-and-pricing:1:abc123",
    "excerpt": "A per-person price is charged for every participant.",
    "score": 0.83,
}


def rag_data(**changes: Any) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "run_id": "rag_01",
        "correlation_id": "ignored",
        "answer": "Per-person prices scale with the party; flat admission does not.",
        "confidence_category": "high",
        "insufficient_context": False,
        "citations": [CITATION],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 3,
            "maximum_score": 0.83,
        },
        **changes,
    }


INSUFFICIENT = rag_data(
    answer="There is not enough indexed context to answer this question.",
    confidence_category="insufficient_context",
    insufficient_context=True,
    citations=[],
    retrieval={"requested_top_k": 5, "returned_chunks": 0, "maximum_score": None},
)


def ask(
    handler: httpx.MockTransport | None,
    *,
    question: str = "How is a per-person price totalled?",
    **settings: Any,
) -> httpx.Response:
    config = {"rag_url": "http://rag.test", "rag_enabled": True, **settings}
    with TestClient(
        create_app(
            Settings(**config),
            database_transport=httpx.MockTransport(FakeDatabase().handle),
            location_transport=httpx.MockTransport(location_handler),
            rag_transport=handler,
        )
    ) as client:
        response: httpx.Response = client.post(
            "/activity/knowledge", json={"question": question}
        )
    return response


def responding(
    status: int, body: object, requests: list[dict[str, Any]] | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/query"
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def test_grounded_answer_keeps_citations_and_confidence() -> None:
    requests: list[dict[str, Any]] = []
    response = ask(
        responding(200, {"data": rag_data()}, requests),
        question="  How is a per-person price totalled?  ",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["confidence_category"] == "high"
    assert body["answer"].startswith("Per-person prices")
    assert body["citations"][0]["title"] == "Activity Booking and Pricing Guide"
    assert "score" not in body["citations"][0]
    assert body["retrieval"]["maximum_score"] == 0.83
    assert body["request_id"].startswith("student4-rag-")
    assert requests == [
        {
            "query": "How is a per-person price totalled?",
            "feature": "student-4",
            "top_k": 5,
            "correlation_id": body["request_id"],
        }
    ]


def test_insufficient_context_is_reported_without_citations() -> None:
    body = ask(responding(200, {"data": INSUFFICIENT})).json()

    assert body["status"] == "insufficient_context"
    assert body["confidence_category"] == "insufficient_context"
    assert body["citations"] == []
    assert body["answer"].startswith("There is not enough indexed context")


def test_answer_without_citations_is_treated_as_insufficient_context() -> None:
    body = ask(responding(200, {"data": rag_data(citations=[])})).json()

    assert body["status"] == "insufficient_context"
    assert body["citations"] == []


def test_disabled_rag_never_calls_the_server() -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise AssertionError

    body = ask(httpx.MockTransport(fail), rag_enabled=False).json()

    assert body["status"] == "disabled"
    assert "disabled" in body["error"]


def test_unconfigured_url_reports_a_safe_error() -> None:
    body = ask(None, rag_url=None).json()

    assert body["status"] == "error"
    assert body["error"] == "The activity knowledge service is not configured."


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (
            503,
            {"error": {"code": "INDEX_NOT_READY", "message": "secret path"}},
            "The activity knowledge index is not ready.",
        ),
        (
            503,
            {"error": {"code": "DEPENDENCY_UNAVAILABLE"}},
            "The activity knowledge service is unavailable.",
        ),
        (
            504,
            {"error": {"code": "DEPENDENCY_TIMEOUT"}},
            "The activity knowledge service timed out.",
        ),
        (
            422,
            {"error": {"code": "VALIDATION_ERROR"}},
            "The activity knowledge service could not accept that question.",
        ),
        (
            500,
            {"detail": "Traceback..."},
            "The activity knowledge service failed to answer.",
        ),
        (
            200,
            {"data": {"answer": "missing fields"}},
            "The activity knowledge service returned a malformed response.",
        ),
        (
            200,
            {"data": rag_data(schema_version="2")},
            "The activity knowledge service returned a malformed response.",
        ),
    ],
)
def test_upstream_failures_map_to_safe_messages(
    status: int, body: object, message: str
) -> None:
    result = ask(responding(status, body)).json()

    assert result["status"] == "error"
    assert result["error"] == message


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            httpx.ConnectError("refused"),
            "The activity knowledge service is unavailable.",
        ),
        (
            httpx.ReadTimeout("slow"),
            "The activity knowledge service timed out.",
        ),
    ],
)
def test_transport_failures_map_to_safe_messages(
    error: httpx.RequestError, message: str
) -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        raise error

    result = ask(httpx.MockTransport(handle)).json()

    assert result == {
        "status": "error",
        "request_id": result["request_id"],
        "answer": None,
        "confidence_category": None,
        "citations": [],
        "retrieval": None,
        "run_id": None,
        "error": message,
    }


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_invalid_questions_are_rejected(question: str) -> None:
    response = ask(responding(200, {"data": rag_data()}), question=question)

    assert response.status_code == 400
