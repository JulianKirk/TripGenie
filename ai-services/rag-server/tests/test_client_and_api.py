from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from conftest import FakeAiMode, write_manifest
from fastapi.testclient import TestClient
from rag_service.ai_mode_client import AiModeClient
from rag_service.app import create_app
from rag_service.errors import ApiError
from rag_service.index import RagIndex


def _ready_response() -> dict[str, object]:
    return {
        "data": {
            "status": "ok",
            "service": "ai-mode",
            "dependencies": {
                "ollama": {
                    "status": "ok",
                    "service": "ollama",
                    "detail": "Models available.",
                    "code": None,
                }
            },
        }
    }


def _embed_response(
    *,
    embeddings: list[list[float]] | None = None,
) -> dict[str, object]:
    vectors = embeddings or [[1.0, 0.0]]
    return {
        "data": {
            "run_id": "aimode_embed",
            "correlation_id": "query-1",
            "model": "nomic-embed-text",
            "provider": "ollama",
            "dimension": len(vectors[0]),
            "embeddings": vectors,
        }
    }


def test_ai_mode_client_validates_health_embed_and_generate(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ready":
            return httpx.Response(200, json=_ready_response())
        if request.url.path == "/embed":
            return httpx.Response(200, json=_embed_response())
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "aimode_generate",
                    "correlation_id": "query-1",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": '{"answer":"Yes","citation_ids":["c1"]}',
                    "done": True,
                }
            },
        )

    client = AiModeClient(settings, transport=httpx.MockTransport(handler))
    health = asyncio.run(client.health())
    embedded = asyncio.run(client.embed(["query"], correlation_id="query-1"))
    generated = asyncio.run(
        client.generate("prompt", {"type": "object"}, correlation_id="query-1")
    )
    asyncio.run(client.close())

    assert health.status == "ok"
    assert embedded.embeddings == [[1.0, 0.0]]
    assert generated.done is True


@pytest.mark.parametrize(
    "response",
    [
        _embed_response(embeddings=[[1.0]]),
        _embed_response(embeddings=[[float("nan"), 0.0], [1.0, 0.0]]),
    ],
)
def test_ai_mode_client_rejects_incompatible_embeddings(
    settings,
    response: dict[str, object],
) -> None:
    client = AiModeClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=json.dumps(response).encode(),
                headers={"content-type": "application/json"},
            )
        ),
    )

    with pytest.raises(ApiError) as raised:
        asyncio.run(client.embed(["one", "two"], correlation_id="query-1"))
    asyncio.run(client.close())

    assert raised.value.code == "BAD_GATEWAY"


def test_ai_mode_client_maps_timeout_and_structured_error(settings) -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        message = "timed out"
        raise httpx.ReadTimeout(message, request=request)

    timeout_client = AiModeClient(
        settings,
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(ApiError) as timeout:
        asyncio.run(timeout_client.embed(["query"], correlation_id="query-1"))
    asyncio.run(timeout_client.close())

    error_client = AiModeClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                503,
                json={
                    "error": {
                        "code": "DEPENDENCY_UNAVAILABLE",
                        "message": "Provider unavailable.",
                        "details": [{"field": "ai_mode", "issue": "offline"}],
                    }
                },
            )
        ),
    )
    with pytest.raises(ApiError) as unavailable:
        asyncio.run(error_client.embed(["query"], correlation_id="query-1"))
    asyncio.run(error_client.close())

    assert timeout.value.code == "DEPENDENCY_TIMEOUT"
    assert unavailable.value.code == "DEPENDENCY_UNAVAILABLE"
    assert unavailable.value.retryable is True


def test_ai_mode_client_rejects_incomplete_generation(settings) -> None:
    client = AiModeClient(
        settings,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "data": {
                        "run_id": "aimode_generate",
                        "correlation_id": "query-1",
                        "model": "qwen2.5:0.5b",
                        "provider": "ollama",
                        "response": "{}",
                        "done": False,
                    }
                },
            )
        ),
    )

    with pytest.raises(ApiError) as raised:
        asyncio.run(
            client.generate(
                "prompt",
                {"type": "object"},
                correlation_id="query-1",
            )
        )
    asyncio.run(client.close())

    assert raised.value.code == "BAD_GATEWAY"


def _seed_index(settings) -> None:
    source = settings.repository_root / "docs" / "guide.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Rules\nGrounded rule.", encoding="utf-8")
    write_manifest(
        settings.manifest_path,
        [
            {
                "source_id": "guide",
                "path": "docs/guide.md",
                "title": "Guide",
                "feature": "shared",
            }
        ],
    )
    asyncio.run(RagIndex(settings).rebuild(FakeAiMode()))


def test_public_health_ready_and_grounded_query_contract(settings) -> None:
    _seed_index(settings)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/ready":
            return httpx.Response(200, json=_ready_response())
        if request.url.path == "/embed":
            body = json.loads(request.content)
            response = _embed_response()
            response["data"]["correlation_id"] = body["correlation_id"]
            return httpx.Response(200, json=response)
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "aimode_generate",
                    "correlation_id": "public-query",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": (
                        '{"answer":"Grounded rule.","citation_ids":'
                        '["guide:0:0cbb75bf7a24"]}'
                    ),
                    "done": True,
                }
            },
        )

    index_result = RagIndex(settings).search(
        [1.0, 0.0],
        feature="shared",
        limit=1,
    )[0]

    def grounded_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/generate":
            return handler(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "aimode_generate",
                    "correlation_id": "public-query",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": json.dumps(
                        {
                            "answer": "Grounded rule.",
                            "citation_ids": [index_result.chunk_id],
                        }
                    ),
                    "done": True,
                }
            },
        )

    app = create_app(
        settings,
        ai_mode_transport=httpx.MockTransport(grounded_handler),
    )
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        query = client.post(
            "/query",
            json={
                "query": "What is the rule?",
                "feature": "student-1",
                "correlation_id": "public-query",
            },
        )

    assert health.status_code == 200
    assert health.json()["data"]["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"
    assert query.status_code == 200
    assert query.json()["data"]["answer"] == "Grounded rule."
    assert query.json()["data"]["citations"][0]["chunk_id"] == index_result.chunk_id
    assert requests.count("/embed") == 1


def test_public_api_reports_not_ready_and_validation_errors(settings) -> None:
    app = create_app(
        settings,
        ai_mode_transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_ready_response())
        ),
    )

    with TestClient(app) as client:
        ready = client.get("/ready")
        invalid = client.post("/query", json={"query": "   "})

    assert ready.status_code == 503
    assert ready.json()["data"]["status"] == "not_ready"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert invalid.json()["error"]["retryable"] is False


def test_public_readiness_reports_unavailable_ai_mode(settings) -> None:
    _seed_index(settings)
    app = create_app(
        settings,
        ai_mode_transport=httpx.MockTransport(
            lambda _: httpx.Response(503, json={"error": "offline"})
        ),
    )

    with TestClient(app) as client:
        ready = client.get("/ready")

    assert ready.status_code == 503
    assert ready.json()["data"]["status"] == "not_ready"
    dependency = ready.json()["data"]["dependencies"]["ai_mode"]
    assert dependency["status"] == "unavailable"
    assert dependency["code"] == "DEPENDENCY_UNAVAILABLE"
