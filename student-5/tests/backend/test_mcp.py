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
    "providers": {"accommodation": {"status": "unavailable", "subtotal": None}},
}


def tool_result(structured: dict, *, is_error: bool = False) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "student5-mcp-000000000000",
        "result": {
            "content": [{"type": "text", "text": json.dumps(structured)}],
            "structuredContent": structured,
            "isError": is_error,
        },
    }


def success(data: dict) -> dict:
    return tool_result(
        {"ok": True, "data": data, "correlation_id": "mcp-1", "source": "student-5"}
    )


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
            replace(settings, mcp_enabled=enabled, mcp_base_url="http://mcp.test/mcp"),
            database_transport=httpx.MockTransport(missing_budget_database),
            mcp_transport=httpx.MockTransport(handler),
        )
    )


def run(
    client: TestClient, action: str = "budget-summary", budget_id: str = BUDGET_ID
) -> httpx.Response:
    return client.post(f"/api/budgets/{budget_id}/mcp/{action}")


def test_budget_summary_action_calls_registered_tool(settings: Settings) -> None:
    handler, requests = recording(success(SUMMARY))
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["action"] == "budget-summary"
    assert data["tool"] == "budgets_get_summary"
    assert data["correlation_id"].startswith("student5-mcp-")
    assert isinstance(data["duration_ms"], int)
    assert data["result"] == SUMMARY
    sent = json.loads(requests[0].content)
    assert requests[0].url.path == "/mcp"
    assert "application/json" in requests[0].headers["accept"]
    assert "text/event-stream" in requests[0].headers["accept"]
    assert sent["method"] == "tools/call"
    assert sent["params"] == {
        "name": "budgets_get_summary",
        "arguments": {"budget_id": BUDGET_ID},
    }


def test_expenses_action_derives_trip_from_budget(settings: Settings) -> None:
    handler, requests = recording(
        success({"expenses": [], "count": 0, "truncated": False})
    )
    with mcp_app(settings, handler) as client:
        response = run(client, "expenses")

    assert response.status_code == 200
    assert json.loads(requests[0].content)["params"] == {
        "name": "expenses_list",
        "arguments": {"trip_id": "trip_chunk3", "limit": 20},
    }


def test_disabled_mcp_makes_no_outbound_call(settings: Settings) -> None:
    handler, requests = recording(success(SUMMARY))
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
    handler, requests = recording(success(SUMMARY))
    with mcp_app(settings, handler) as client:
        response = run(client, action)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert requests == []


def test_missing_budget_returns_404_before_mcp(settings: Settings) -> None:
    handler, requests = recording(success(SUMMARY))
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


def test_unregistered_tool_is_reported_as_unavailable(settings: Settings) -> None:
    unknown = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "content": [{"type": "text", "text": "Unknown tool: budgets_get_summary"}],
            "isError": True,
        },
    }
    handler, _ = recording(unknown)
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 503
    assert response.json()["error"]["details"] == [
        {"field": "mcp", "issue": "tool not registered"}
    ]


def test_structured_tool_error_is_passed_through_safely(settings: Settings) -> None:
    handler, _ = recording(
        tool_result(
            {
                "ok": False,
                "error": {
                    "code": "PROVIDER_UNAVAILABLE",
                    "message": "Provider unreachable",
                    "retryable": True,
                },
                "correlation_id": "mcp-1",
                "source": "student-5",
            },
            is_error=True,
        )
    )
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "MCP_TOOL_ERROR"
    assert error["message"] == "Provider unreachable"
    assert error["details"] == [{"field": "mcp", "issue": "PROVIDER_UNAVAILABLE"}]


@pytest.mark.parametrize(
    ("payload", "status_code"),
    [
        ({"jsonrpc": "2.0", "id": "1", "error": {"code": -32602}}, 200),
        (tool_result({"ok": True, "data": ["not", "an", "object"]}), 200),
        (tool_result({"unexpected": True}), 200),
        ({"jsonrpc": "2.0", "id": "1", "result": {"isError": True}}, 200),
        (success({"blob": "x" * 33000}), 200),
        ({"detail": "Not Acceptable"}, 406),
    ],
)
def test_malformed_or_oversized_results_return_bad_gateway(
    settings: Settings, payload: dict, status_code: int
) -> None:
    handler, _ = recording(payload, status_code)
    with mcp_app(settings, handler) as client:
        response = run(client)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INVALID_DEPENDENCY_RESPONSE"


def test_logs_exclude_tool_payloads(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    handler, _ = recording(success(SUMMARY))
    with caplog.at_level(logging.INFO), mcp_app(settings, handler) as client:
        run(client)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "action=budget-summary outcome=ok" in messages
    assert "699.70" not in messages
