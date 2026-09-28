from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_mode_service.app import create_app
from ai_mode_service.config import Settings


def success_generate_response(
    *,
    model: str = "qwen2.5:0.5b",
    response_text: str = '{"suggestions":[]}',
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "created_at": "2026-08-31T11:00:00Z",
            "response": response_text,
            "done": True,
            "done_reason": "stop",
            "context": [1, 2, 3],
            "total_duration": 5043500667,
            "load_duration": 5025959,
            "prompt_eval_count": 26,
            "prompt_eval_duration": 325953000,
            "eval_count": 290,
            "eval_duration": 4709213000,
        },
    )


class FakeOllamaApi:
    def __init__(self) -> None:
        self.tag_requests = 0
        self.generate_requests: list[dict[str, object]] = []
        self.models = [
            {
                "name": "qwen2.5:0.5b",
                "model": "qwen2.5:0.5b",
                "modified_at": "2026-08-31T11:00:00Z",
                "size": 934348800,
                "digest": "sha256:qwen-demo",
                "details": {
                    "family": "qwen2",
                    "families": ["qwen2"],
                    "parameter_size": "0.5B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {
                "name": "nomic-embed-text:latest",
                "model": "nomic-embed-text:latest",
                "modified_at": "2026-08-31T11:00:00Z",
                "size": 274000000,
                "digest": "sha256:nomic-demo",
                "details": {
                    "family": "nomic-bert",
                    "families": ["nomic-bert"],
                    "parameter_size": "137M",
                    "quantization_level": "F16",
                },
            },
            {
                "name": "llama3.1:8b",
                "model": "llama3.1:8b",
                "modified_at": "2026-08-31T11:00:00Z",
                "size": 4800000000,
                "digest": "sha256:llama-demo",
                "details": {
                    "family": "llama",
                    "families": ["llama"],
                    "parameter_size": "8B",
                    "quantization_level": "Q4_K_M",
                },
            },
        ]
        self._tag_responses: list[httpx.Response | Exception] = []
        self._generate_responses: list[httpx.Response | Exception] = []
        self.embed_requests: list[dict[str, object]] = []
        self._embed_responses: list[httpx.Response | Exception] = []

    def queue_tag_response(self, response: httpx.Response | Exception) -> None:
        self._tag_responses.append(response)

    def queue_generate_response(self, response: httpx.Response | Exception) -> None:
        self._generate_responses.append(response)

    def queue_embed_response(self, response: httpx.Response | Exception) -> None:
        self._embed_responses.append(response)

    def handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method.upper()
        path = request.url.path

        if path == "/api/tags" and method == "GET":
            self.tag_requests += 1
            if self._tag_responses:
                queued = self._tag_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued
            return httpx.Response(200, json={"models": deepcopy(self.models)})

        if path == "/api/generate" and method == "POST":
            self.generate_requests.append(self._request_json(request))
            if self._generate_responses:
                queued = self._generate_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued
            return success_generate_response()

        if path == "/api/embed" and method == "POST":
            request_json = self._request_json(request)
            self.embed_requests.append(request_json)
            if self._embed_responses:
                queued = self._embed_responses.pop(0)
                if isinstance(queued, Exception):
                    raise queued
                return queued
            inputs = request_json.get("input", [])
            return httpx.Response(
                200,
                json={
                    "model": request_json.get("model", "nomic-embed-text"),
                    "embeddings": [[1.0, 0.0, 0.5] for _ in inputs],
                },
            )

        return httpx.Response(404, json={"error": "not found"})

    @staticmethod
    def _request_json(request: httpx.Request) -> dict[str, object]:
        if not request.content:
            return {}
        return json.loads(request.content.decode("utf-8"))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        service_name="ai-mode",
        ollama_base_url="http://ollama.test",
        default_model="qwen2.5:0.5b",
        allowed_models=("qwen2.5:0.5b", "llama3.1:8b"),
        default_embedding_model="nomic-embed-text",
        allowed_embedding_models=("nomic-embed-text",),
        ollama_timeout_seconds=1.0,
        max_prompt_chars=80,
        max_schema_chars=180,
        max_response_bytes=120,
        max_embed_inputs=3,
        max_embed_input_chars=40,
        max_embed_dimensions=8,
    )


@pytest.fixture
def ollama_api() -> FakeOllamaApi:
    return FakeOllamaApi()


@pytest.fixture
def client_factory(settings: Settings):
    def factory(
        *,
        settings_override: Settings | None = None,
        ollama_handler=None,
    ) -> Iterator[TestClient]:
        app = create_app(
            settings_override or settings,
            ollama_transport=(
                httpx.MockTransport(ollama_handler) if ollama_handler else None
            ),
        )
        return TestClient(app)

    return factory
