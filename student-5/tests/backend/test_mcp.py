from __future__ import annotations

import json
import logging
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings

from .conftest import BUDGET_ID, database_handler

MISSING_BUDGET_ID = "33333333-3333-4333-8333-333333333333"
SUMMARY = {
    "budget_id": BUDGET_ID,
    "trip_id": "trip_chunk3",
    "currency": "AUD",
    "total_budget": "1000.00",
    "remaining_budget": "699.70",
}
TOOL_CALL = {
    "tool": "budgets_get_summary",
    "arguments": {"budget_id": BUDGET_ID},
    "status": "success",
    "duration_ms": 40,
    "result": {
        "structuredContent": {"ok": True, "data": SUMMARY, "source": "student-5"},
        "isError": False,
    },
}


def generate_response(tools: list[dict], response: str = "Remaining is AUD 699.70."):
    return {
        "data": {
            "run_id": "aimode_1",
            "correlation_id": "student5-mcp-000000000000",
            "model": "llama3.1:8b",
            "provider": "ollama",
            "response": response,
            "done": True,
            "tools": tools,
        }
    }


def recording(payload: dict, status_code: int = 200):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json=payload)

    return handler, requests


def missing_budget_database(request: httpx.Request) -> httpx.Response:
    if request.url.path == f"/internal/budgets/{MISSING_BUDGET_ID}":
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Budget not found.",
                    "details": [],
                }
            },
        )
    return database_handler(request)


def mcp_app(settings: Settings, handler, *, enabled: bool = True) -> TestClient:
    return TestClient(
        create_app(
            replace(settings, mcp_enabled=enabled),
            database_transport=httpx.MockTransport(missing_budget_database),
            ai_mode_transport=httpx.MockTransport(handler),
        )
    )


def run(
    client: TestClient, action: str = "budget-summary", budget_id: str = BUDGET_ID
) -> httpx.Response:
    return client.post(f"/api/budgets/{budget_id}/mcp/{action}")


def test_budget_summary_action_goes_through_ai_mode_and_returns_tool_trace(
    settings: Settings,
) -> None:
    handler, requests = recording(generate_response([TOOL_CALL]))
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["action"] == "budget-summary"
    assert data["correlation_id"].startswith("student5-mcp-")
    assert isinstance(data["duration_ms"], int)
    assert data["answer"] == "Remaining is AUD 699.70."
    assert data["run_id"] == "aimode_1"
    assert data["model"] == "llama3.1:8b"
    assert data["tools"][0]["tool"] == "budgets_get_summary"
    assert data["tools"][0]["result"] == TOOL_CALL["result"]
    assert len(requests) == 1
    assert requests[0].url.path == "/generate"
    sent = json.loads(requests[0].content)
    assert sent["correlation_id"] == data["correlation_id"]
    assert "schema" not in sent
    assert json.loads(sent["prompt"]) == {
        "request": "Get the spending summary for this budget.",
        "budget_id": BUDGET_ID,
        "trip_id": "trip_chunk3",
    }
    assert "native MCP functions" in sent["system"]
    assert sent["metadata"]["feature"] == "student-5-budget-tools"


def test_expenses_action_prompts_with_trip_from_budget(settings: Settings) -> None:
    handler, requests = recording(generate_response([]))
    with mcp_app(settings, handler) as client:
        response = run(client, "expenses")

    assert response.status_code == 200
    assert response.json()["data"]["tools"] == []
    prompt = json.loads(json.loads(requests[0].content)["prompt"])
    assert prompt["request"] == "List the 20 most recent expenses for this trip."
    assert prompt["trip_id"] == "trip_chunk3"


def test_failed_tool_call_is_returned_not_hidden(settings: Settings) -> None:
    failed = {
        "tool": "budgets_get_summary",
        "arguments": {"budget_id": BUDGET_ID},
        "status": "error",
        "duration_ms": 5,
        "error": "Provider unreachable",
    }
    handler, _ = recording(generate_response([failed], "The tool failed."))
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 200
    call = response.json()["data"]["tools"][0]
    assert call["status"] == "error"
    assert call["error"] == "Provider unreachable"
    assert call["result"] is None


def test_disabled_mcp_makes_no_outbound_call(settings: Settings) -> None:
    handler, requests = recording(generate_response([TOOL_CALL]))
    with mcp_app(settings, handler, enabled=False) as client:
        response = run(client)
        health = client.get("/health").json()["data"]

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MCP_DISABLED"
    assert requests == []
    assert health["integrations"]["mcp"] == "disabled"


@pytest.mark.parametrize("action", ["budgets_delete", "unknown", "budget-summary2"])
def test_unknown_action_is_rejected_without_a_call(
    settings: Settings, action: str
) -> None:
    handler, requests = recording(generate_response([TOOL_CALL]))
    with mcp_app(settings, handler) as client:
        response = run(client, action)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert requests == []


def test_missing_budget_returns_404_before_ai_mode(settings: Settings) -> None:
    handler, requests = recording(generate_response([TOOL_CALL]))
    with mcp_app(settings, handler) as client:
        response = run(client, budget_id=MISSING_BUDGET_ID)
        malformed = run(client, budget_id="not-a-uuid")

    assert response.status_code == 404
    assert malformed.status_code == 422
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

    with mcp_app(settings, handler) as client:
        response = run(client)
        ready = client.get("/ready")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert ready.status_code == 200


@pytest.mark.parametrize(
    ("payload", "status_code"),
    [
        ({"data": {"unexpected": True}}, 200),
        (generate_response([{"tool": "x", "status": "maybe"}]), 200),
        (
            generate_response([TOOL_CALL])
            | {"data": generate_response([])["data"] | {"done": False}},
            200,
        ),
        ({"error": {"code": "UPSTREAM_BAD", "message": "bad"}}, 502),
    ],
)
def test_malformed_ai_mode_results_return_bad_gateway(
    settings: Settings, payload: dict, status_code: int
) -> None:
    handler, _ = recording(payload, status_code)
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 502


def test_logs_exclude_tool_payloads(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    handler, _ = recording(generate_response([TOOL_CALL]))
    with caplog.at_level(logging.INFO), mcp_app(settings, handler) as client:
        run(client)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "action=budget-summary outcome=ok" in messages
    assert "699.70" not in messages
