from __future__ import annotations

import json

import httpx
import pytest
from backend_service.config import Settings
from conftest import create_trip_payload, error_response

ENABLED = Settings(database_api_base_url="http://database.test", rag_enabled=True)
CITATION = {
    "source_id": "student-1-rules",
    "path": "docs/architecture/student-1.md",
    "title": "Student 1 rules",
    "section": "Itinerary",
    "chunk_id": "student-1-rules:0",
    "excerpt": "Items must fall within the trip dates.",
}


def rag_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1",
        "run_id": "run-1",
        "correlation_id": "student1-rag-abc",
        "answer": "Items must fall within the trip dates.",
        "confidence_category": "high",
        "insufficient_context": False,
        "citations": [CITATION],
        "retrieval": {
            "requested_top_k": 5,
            "returned_chunks": 1,
            "maximum_score": 0.84,
        },
    }
    payload.update(overrides)
    return payload


class FakeRag:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def make(client_factory, database_api):
    def _make(response, settings=ENABLED):
        rag = FakeRag(response)
        client = client_factory(
            database_api.handle, settings_override=settings, rag_handler=rag.handle
        )
        return client, rag

    return _make


def _trip(client) -> str:
    return client.post("/api/trips", json=create_trip_payload()).json()["data"]["id"]


def test_grounded_answer_is_passed_through(make) -> None:
    client, rag = make(httpx.Response(200, json={"data": rag_payload()}))
    with client:
        trip_id = _trip(client)
        response = client.post(
            f"/api/trips/{trip_id}/rag-query",
            json={"question": "  What limits apply to items?  "},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trip_id"] == trip_id
    assert data["answer"] == "Items must fall within the trip dates."
    assert data["confidence_category"] == "high"
    assert data["insufficient_context"] is False
    assert data["citations"] == [CITATION]
    sent = rag.requests[0]
    assert sent["query"] == "What limits apply to items?"
    assert sent["feature"] == "student-1"
    assert str(sent["correlation_id"]).startswith("student1-rag-")


def test_insufficient_context_is_passed_through(make) -> None:
    payload = rag_payload(
        answer="There is not enough indexed context to answer this question.",
        confidence_category="insufficient_context",
        insufficient_context=True,
        citations=[],
    )
    client, _ = make(httpx.Response(200, json={"data": payload}))
    with client:
        trip_id = _trip(client)
        response = client.post(
            f"/api/trips/{trip_id}/rag-query", json={"question": "Weather?"}
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["insufficient_context"] is True
    assert data["confidence_category"] == "insufficient_context"
    assert data["citations"] == []


def test_disabled_is_an_explicit_error(make) -> None:
    client, rag = make(
        httpx.Response(200, json={"data": rag_payload()}),
        settings=Settings(database_api_base_url="http://database.test"),
    )
    with client:
        trip_id = _trip(client)
        response = client.post(
            f"/api/trips/{trip_id}/rag-query", json={"question": "Anything?"}
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RAG_DISABLED"
    assert rag.requests == []


@pytest.mark.parametrize(
    ("upstream", "status", "code"),
    [
        (httpx.ReadTimeout("slow"), 504, "DEPENDENCY_TIMEOUT"),
        (httpx.ConnectError("down"), 503, "DEPENDENCY_UNAVAILABLE"),
        (error_response(503, "INDEX_NOT_READY", "no index"), 503, "INDEX_NOT_READY"),
        (
            error_response(503, "DEPENDENCY_UNAVAILABLE", "no ai"),
            503,
            "DEPENDENCY_UNAVAILABLE",
        ),
        (error_response(504, "DEPENDENCY_TIMEOUT", "slow"), 504, "DEPENDENCY_TIMEOUT"),
        (error_response(500, "INTERNAL", "boom"), 502, "BAD_GATEWAY"),
        (httpx.Response(200, json={"data": {"answer": "x"}}), 502, "BAD_GATEWAY"),
        (
            httpx.Response(200, json={"data": rag_payload(citations=[])}),
            502,
            "BAD_GATEWAY",
        ),
        (
            httpx.Response(200, json={"data": rag_payload(schema_version="2")}),
            502,
            "BAD_GATEWAY",
        ),
        (httpx.Response(200, text="not json"), 502, "BAD_GATEWAY"),
    ],
)
def test_upstream_failures_map_to_stable_errors(make, upstream, status, code) -> None:
    client, _ = make(upstream)
    with client:
        trip_id = _trip(client)
        response = client.post(
            f"/api/trips/{trip_id}/rag-query", json={"question": "Anything?"}
        )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_unknown_trip_is_404_without_querying(make) -> None:
    client, rag = make(httpx.Response(200, json={"data": rag_payload()}))
    with client:
        response = client.post(
            "/api/trips/trip_missing/rag-query", json={"question": "Anything?"}
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert rag.requests == []


@pytest.mark.parametrize(
    "body",
    [{}, {"question": "   "}, {"question": "x" * 2001}, {"question": "ok", "k": 1}],
)
def test_invalid_question_is_rejected(make, body) -> None:
    client, rag = make(httpx.Response(200, json={"data": rag_payload()}))
    with client:
        trip_id = _trip(client)
        response = client.post(f"/api/trips/{trip_id}/rag-query", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rag.requests == []


def test_ready_ignores_enabled_but_unreachable_rag_and_mcp(
    client_factory, database_api
) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"readiness must not call {request.url}")

    settings = Settings(
        database_api_base_url="http://database.test",
        rag_enabled=True,
        mcp_enabled=True,
    )
    with client_factory(
        database_api.handle,
        settings_override=settings,
        rag_handler=unreachable,
    ) as client:
        ready = client.get("/ready")
        health = client.get("/health")

    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ok"
    assert health.status_code == 200
