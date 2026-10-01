"""Release 1: grounded transport answers through the shared RAG server.

The RAG server is replaced by a fake behind an injected transport, so these
tests pin this service's side of the contract -- the fixed feature scope, the
pass-through of citations and confidence, and how each failure surfaces --
without a live host server.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

TRIPS_BASE_URL = "http://student-1-backend:8001"
QUESTION = "How is the estimated cost worked out for a car rental?"

CITATION = {
    "source_id": "transport-pricing-and-costs",
    "path": "ai-services/rag-server/knowledge/transport/pricing-and-costs.md",
    "title": "Transport Pricing and Cost Estimates",
    "section": "Transport pricing: per traveller and per vehicle",
    "chunk_id": "transport-pricing-and-costs:0002",
    "excerpt": "A per-vehicle price is charged once for the whole party.",
}


def grounded(correlation_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "run_id": "rag_run_0001",
        "correlation_id": correlation_id,
        "answer": "A car rental is priced per vehicle, so it is not multiplied.",
        "confidence_category": "high",
        "insufficient_context": False,
        "citations": [CITATION],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 1,
            "maximum_score": 0.86,
        },
    }


def insufficient(correlation_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "run_id": "rag_run_0002",
        "correlation_id": correlation_id,
        "answer": "There is not enough indexed context to answer this question.",
        "confidence_category": "insufficient_context",
        "insufficient_context": True,
        "citations": [],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 0,
            "maximum_score": 0.31,
        },
    }


Reply = Callable[[httpx.Request, dict[str, Any]], httpx.Response]


class FakeRag:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reply: Reply = lambda _request, body: httpx.Response(
            200,
            json={"data": grounded(body["correlation_id"])},
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(
            {
                "url": str(request.url),
                "body": body,
                "headers": dict(request.headers),
            },
        )
        return self.reply(request, body)


@pytest.fixture
def fake_rag() -> FakeRag:
    return FakeRag()


def _client(
    settings: Settings,
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
    fake_rag: FakeRag,
) -> Iterator[TestClient]:
    app = create_app(
        settings,
        transport=database_transport,
        trips_transport=itinerary_transport,
        rag_transport=httpx.MockTransport(fake_rag.handle),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def rag_client(
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
    fake_rag: FakeRag,
) -> Iterator[TestClient]:
    settings = Settings(
        database_api_base_url="http://student-3-database:8004",
        trips_api_base_url=TRIPS_BASE_URL,
        rag_enabled=True,
        rag_base_url="http://host.docker.internal:8011",
    )
    yield from _client(settings, database_transport, itinerary_transport, fake_rag)


@pytest.fixture
def disabled_client(
    settings: Settings,
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
    fake_rag: FakeRag,
) -> Iterator[TestClient]:
    yield from _client(settings, database_transport, itinerary_transport, fake_rag)


def _ask(client: TestClient, payload: object) -> httpx.Response:
    return client.post("/api/transport-options/rag-query", json=payload)


# ----------------------------------------------------------------- health


def test_health_reports_rag_disabled_by_default(disabled_client: TestClient) -> None:
    body = disabled_client.get("/health").json()["data"]

    assert body["integrations"] == {"rag": "disabled", "mcp": "disabled"}


def test_readiness_never_contacts_rag(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    response = rag_client.get("/ready")

    assert response.status_code == 200
    assert response.json()["data"]["integrations"]["rag"] == "enabled"
    assert fake_rag.calls == []


# --------------------------------------------------------------- grounded


def test_a_grounded_answer_is_passed_through_with_citations_and_confidence(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    response = _ask(rag_client, {"question": f"  {QUESTION}  "})

    assert response.status_code == 200
    answer = response.json()["data"]
    assert answer["insufficient_context"] is False
    assert answer["confidence_category"] == "high"
    assert answer["citations"] == [CITATION]
    assert answer["retrieval"]["returned_chunks"] == 1
    assert answer["run_id"] == "rag_run_0001"

    (call,) = fake_rag.calls
    assert call["url"] == "http://host.docker.internal:8011/query"
    assert call["body"]["query"] == QUESTION
    assert call["body"]["feature"] == "student-3"
    assert call["body"]["top_k"] == 5
    assert re.fullmatch(r"student3-rag-[0-9a-f]{12}", call["body"]["correlation_id"])
    assert call["headers"]["x-request-id"] == call["body"]["correlation_id"]
    assert answer["correlation_id"] == call["body"]["correlation_id"]


def test_insufficient_context_is_a_normal_answer_without_citations(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    fake_rag.reply = lambda _request, body: httpx.Response(
        200,
        json={"data": insufficient(body["correlation_id"])},
    )

    response = _ask(rag_client, {"question": "Who won the Melbourne Cup?"})

    assert response.status_code == 200
    answer = response.json()["data"]
    assert answer["insufficient_context"] is True
    assert answer["confidence_category"] == "insufficient_context"
    assert answer["citations"] == []


# ------------------------------------------------------------- boundaries


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": QUESTION, "feature": "student-1"},
        {"question": QUESTION, "top_k": 10},
        {"question": QUESTION, "rag_url": "http://evil.example"},
    ],
)
def test_only_a_bounded_question_reaches_rag(
    rag_client: TestClient,
    fake_rag: FakeRag,
    payload: object,
) -> None:
    response = _ask(rag_client, payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_rag.calls == []


def test_disabled_rag_is_an_explicit_503(
    disabled_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    response = _ask(disabled_client, {"question": QUESTION})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "RAG_DISABLED"
    assert error["message"] == (
        "The transport knowledge assistant is disabled in this environment."
    )
    assert fake_rag.calls == []


def test_transport_browsing_works_while_rag_is_disabled(
    disabled_client: TestClient,
) -> None:
    assert disabled_client.get("/api/transport-options").status_code == 200


# --------------------------------------------------------------- failures


def _error(status_code: int, code: str) -> Reply:
    return lambda _request, _body: httpx.Response(
        status_code,
        json={"error": {"code": code, "message": "upstream", "details": []}},
    )


def _raise(exc_type: type[httpx.RequestError]) -> Reply:
    def reply(request: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
        raise exc_type("stubbed RAG failure", request=request)

    return reply


@pytest.mark.parametrize(
    ("reply", "status_code", "code"),
    [
        (_error(503, "INDEX_NOT_READY"), 503, "INDEX_NOT_READY"),
        (_error(503, "DEPENDENCY_UNAVAILABLE"), 503, "DEPENDENCY_UNAVAILABLE"),
        (_error(504, "DEPENDENCY_TIMEOUT"), 504, "DEPENDENCY_TIMEOUT"),
        (_error(500, "INTERNAL"), 502, "BAD_GATEWAY"),
        (_error(422, "VALIDATION_ERROR"), 502, "BAD_GATEWAY"),
        (_raise(httpx.ConnectError), 503, "DEPENDENCY_UNAVAILABLE"),
        (_raise(httpx.ReadTimeout), 504, "DEPENDENCY_TIMEOUT"),
    ],
)
def test_rag_failures_are_dependency_errors(
    rag_client: TestClient,
    fake_rag: FakeRag,
    reply: Reply,
    status_code: int,
    code: str,
) -> None:
    fake_rag.reply = reply

    response = _ask(rag_client, {"question": QUESTION})

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(schema_version="2"),
        lambda data: data.update(citations=[]),
        lambda data: data.update(confidence_category="certain"),
        lambda data: data.pop("retrieval"),
        lambda data: data.update(
            insufficient_context=True,
            confidence_category="insufficient_context",
        ),
    ],
    ids=[
        "schema-version",
        "grounded-without-citations",
        "unknown-confidence",
        "missing-retrieval",
        "insufficient-with-citations",
    ],
)
def test_a_reply_that_breaks_the_rag_contract_is_refused(
    rag_client: TestClient,
    fake_rag: FakeRag,
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    def reply(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        data = grounded(body["correlation_id"])
        mutate(data)
        return httpx.Response(200, json={"data": data})

    fake_rag.reply = reply

    response = _ask(rag_client, {"question": QUESTION})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BAD_GATEWAY"


def test_questions_and_answers_stay_out_of_the_logs(
    rag_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="student3_backend_service.service"):
        _ask(rag_client, {"question": QUESTION})

    assert "rag_query correlation_id=student3-rag-" in caplog.text
    assert "confidence=high citations=1" in caplog.text
    assert "car rental" not in caplog.text
