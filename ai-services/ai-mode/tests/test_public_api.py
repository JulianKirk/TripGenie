from __future__ import annotations

import logging

import httpx
import pytest

from ai_mode_service.models import CORRELATION_ID_ISSUE
from ai_mode_service.service import _sanitise_log_value


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


def test_health_reports_ok_with_current_ollama_metadata(
    client_factory,
    ollama_api,
) -> None:
    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "status": "ok",
            "service": "ai-mode",
            "dependencies": {
                "ollama": {
                    "status": "ok",
                    "service": "ollama",
                    "detail": (
                        "Ollama responded successfully and the configured model is "
                        "available."
                    ),
                    "code": None,
                }
            },
        }
    }
    assert ollama_api.tag_requests == 1


@pytest.mark.parametrize(
    "queued_response",
    [
        httpx.Response(200, json={}),
        httpx.Response(200, text="{not json"),
    ],
)
def test_health_reports_degraded_for_malformed_model_list(
    client_factory,
    ollama_api,
    queued_response: httpx.Response,
) -> None:
    ollama_api.queue_tag_response(queued_response)

    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "degraded"
    assert response.json()["data"]["dependencies"]["ollama"] == {
        "status": "invalid_response",
        "service": "ollama",
        "detail": "Ollama returned a malformed model list response.",
        "code": "BAD_GATEWAY",
    }


def test_ready_returns_model_unavailable_for_valid_empty_model_list(
    client_factory,
    ollama_api,
) -> None:
    ollama_api.models = []

    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "data": {
            "status": "unavailable",
            "service": "ai-mode",
            "dependencies": {
                "ollama": {
                    "status": "degraded",
                    "service": "ollama",
                    "detail": (
                        "Ollama responded, but the configured model "
                        "'qwen2.5:0.5b' is not available."
                    ),
                    "code": "MODEL_UNAVAILABLE",
                }
            },
        }
    }


def test_generate_uses_non_stream_official_ollama_client_request_shape(
    client_factory,
    ollama_api,
) -> None:
    correlation_id = "student1-run-01"
    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post(
            "/generate",
            json={
                "prompt": "Return JSON only.",
                "schema": {
                    "type": "object",
                    "properties": {"suggestions": {"type": "array"}},
                    "required": ["suggestions"],
                },
                "correlation_id": correlation_id,
                "metadata": {
                    "feature": "student-1-trip-suggestions",
                    "trip_id": "trip_2027_sydney_getaway",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["correlation_id"] == correlation_id
    assert payload["model"] == "qwen2.5:0.5b"
    assert payload["provider"] == "ollama"
    assert payload["done"] is True
    assert payload["response"] == '{"suggestions":[]}'
    assert payload["run_id"].startswith("aimode_")

    ollama_request = ollama_api.generate_requests[0]
    assert ollama_request["model"] == "qwen2.5:0.5b"
    assert ollama_request["prompt"] == "Return JSON only."
    assert ollama_request["raw"] is True
    assert ollama_request["stream"] is False
    assert ollama_request["options"] == {"temperature": 0}
    assert ollama_request["format"]["type"] == "object"


def test_generate_accepts_max_length_correlation_id(client_factory, ollama_api) -> None:
    correlation_id = "A" + ("1" * 63)

    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post(
            "/generate",
            json={
                "prompt": "Return JSON only.",
                "correlation_id": correlation_id,
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["correlation_id"] == correlation_id


@pytest.mark.parametrize(
    "correlation_id",
    ["bad\nvalue", "bad\rvalue", "bad value", "A" * 65],
)
def test_generate_rejects_unsafe_correlation_id(
    client_factory,
    ollama_api,
    correlation_id: str,
) -> None:
    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post(
            "/generate",
            json={
                "prompt": "Return JSON only.",
                "correlation_id": correlation_id,
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {"field": "correlation_id", "issue": CORRELATION_ID_ISSUE}
    ]
    assert ollama_api.generate_requests == []


def test_generate_allows_approved_model_override(
    client_factory,
    ollama_api,
) -> None:
    ollama_api.queue_generate_response(
        success_generate_response(model="llama3.1:8b", response_text="{}")
    )

    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post(
            "/generate",
            json={
                "prompt": "Return JSON only.",
                "model": "llama3.1:8b",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["model"] == "llama3.1:8b"
    assert ollama_api.generate_requests[0]["model"] == "llama3.1:8b"


def test_generate_rejects_unapproved_model_override(client_factory, ollama_api) -> None:
    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post(
            "/generate",
            json={
                "prompt": "Return JSON only.",
                "model": "deepseek-r1:8b",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "One or more fields failed validation.",
        "details": [
            {
                "field": "model",
                "issue": "must be one of: qwen2.5:0.5b, llama3.1:8b",
            }
        ],
    }
    assert ollama_api.generate_requests == []


def test_generate_validates_prompt_and_schema_bounds(
    client_factory,
    ollama_api,
) -> None:
    with client_factory(ollama_handler=ollama_api.handle) as client:
        prompt_response = client.post(
            "/generate",
            json={"prompt": "x" * 81},
        )
        schema_response = client.post(
            "/generate",
            json={
                "prompt": "Return JSON only.",
                "schema": {"payload": "x" * 200},
            },
        )

    assert prompt_response.status_code == 422
    assert prompt_response.json()["error"]["details"] == [
        {"field": "prompt", "issue": "must be at most 80 characters"}
    ]
    assert schema_response.status_code == 422
    assert schema_response.json()["error"]["details"] == [
        {
            "field": "schema",
            "issue": "must serialise to at most 180 characters",
        }
    ]


@pytest.mark.parametrize(
    ("queued_response", "status_code", "error_code", "message_fragment"),
    [
        (
            httpx.ReadTimeout(
                "slow",
                request=httpx.Request("POST", "http://ollama.test/api/generate"),
            ),
            504,
            "DEPENDENCY_TIMEOUT",
            "The AI provider did not respond before the configured timeout.",
        ),
        (
            httpx.ConnectError(
                "boom",
                request=httpx.Request("POST", "http://ollama.test/api/generate"),
            ),
            503,
            "DEPENDENCY_UNAVAILABLE",
            "The AI provider is unavailable.",
        ),
        (
            httpx.Response(404, json={"error": "model 'llama3.1:8b' not found"}),
            503,
            "MODEL_UNAVAILABLE",
            "Requested AI model is not available.",
        ),
        (
            httpx.Response(
                404,
                json={"error": {"message": "model 'llama3.1:8b' not found"}},
            ),
            503,
            "MODEL_UNAVAILABLE",
            "Requested AI model is not available.",
        ),
        (
            httpx.Response(404, json={"error": "not found"}),
            503,
            "DEPENDENCY_UNAVAILABLE",
            "The AI provider could not generate a response.",
        ),
        (
            httpx.Response(200, text="{not json"),
            502,
            "BAD_GATEWAY",
            "The AI provider returned a malformed generate response.",
        ),
        (
            httpx.Response(
                200,
                json={
                    "model": "qwen2.5:0.5b",
                    "response": "",
                    "done": False,
                },
            ),
            502,
            "BAD_GATEWAY",
            "The AI provider returned a malformed generate response.",
        ),
        (
            success_generate_response(response_text="x" * 200),
            502,
            "DEPENDENCY_RESPONSE_TOO_LARGE",
            (
                "The AI provider returned a response that exceeded the "
                "configured size limit."
            ),
        ),
    ],
)
def test_generate_surfaces_stable_provider_failures(
    client_factory,
    ollama_api,
    queued_response: httpx.Response | Exception,
    status_code: int,
    error_code: str,
    message_fragment: str,
) -> None:
    ollama_api.queue_generate_response(queued_response)

    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post("/generate", json={"prompt": "Return JSON only."})

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert message_fragment in response.json()["error"]["message"]


def test_generate_logs_safe_metadata_without_prompt_or_output(
    client_factory,
    ollama_api,
    caplog,
) -> None:
    ollama_api.queue_generate_response(
        success_generate_response(response_text="SENSITIVE_OUTPUT_SHOULD_NOT_BE_LOGGED")
    )

    caplog.set_level(logging.INFO, logger="ai_mode_service.service")
    with client_factory(ollama_handler=ollama_api.handle) as client:
        response = client.post(
            "/generate",
            json={
                "prompt": "SENSITIVE_PROMPT_SHOULD_NOT_BE_LOGGED",
                "correlation_id": "student1-run-02",
                "metadata": {
                    "feature": "student-1-trip-suggestions",
                    "trip_id": "trip_2027_sydney_getaway",
                },
            },
        )

    assert response.status_code == 200
    assert "ai_mode stage=start" in caplog.text
    assert "ai_mode stage=success" in caplog.text
    assert "SENSITIVE_PROMPT_SHOULD_NOT_BE_LOGGED" not in caplog.text
    assert "SENSITIVE_OUTPUT_SHOULD_NOT_BE_LOGGED" not in caplog.text
    assert "trip_2027_sydney_getaway" not in caplog.text


def test_log_sanitiser_replaces_control_characters() -> None:
    assert (
        _sanitise_log_value("safe\nvalue\twith\rcontrols")
        == "safe?value?with?controls"
    )
