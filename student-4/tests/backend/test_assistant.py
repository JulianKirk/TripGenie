from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

ACTIVITY = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
DETAIL: dict[str, Any] = {
    "id": ACTIVITY,
    "name": "Harbour walk",
    "description": "A real walk",
    "price": "45.00",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 60,
    "minimum_participants": 1,
    "booking_required": False,
    "is_active": True,
    "categories": ["OUTDOOR"],
    "location_details": {"country": "australia", "city": "sydney"},
    "availability_schedules": [
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "recurring_weekly": True,
            "day_of_week": "SATURDAY",
            "start_time": "09:00",
            "end_time": "11:00",
        }
    ],
}


class ProtocolFake:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        method = body["method"]
        if "id" not in body:
            return httpx.Response(202)
        result: dict[str, Any]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": name, "description": name, "inputSchema": schema}
                    for name, schema in {
                        "activities_search": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "additionalProperties": False,
                        },
                        "activities_get": {
                            "type": "object",
                            "properties": {
                                "activity_id": {"type": "string", "format": "uuid"}
                            },
                            "required": ["activity_id"],
                            "additionalProperties": False,
                        },
                        "activities_delete": {"type": "object"},
                        "trip_get_context": {
                            "type": "object",
                            "properties": {"trip_id": {"type": "string"}},
                            "required": ["trip_id"],
                            "additionalProperties": False,
                        },
                    }.items()
                ]
            }
        else:
            assert method == "tools/call"
            self.calls.append(body["params"])
            name = body["params"]["name"]
            data = (
                {"items": [DETAIL], "count": 1, "truncated": False}
                if name == "activities_search"
                else DETAIL
            )
            envelope = {
                "ok": True,
                "data": data,
                "correlation_id": "mcp-test",
                "source": "student-4",
            }
            if self.fail:
                envelope = {
                    "ok": False,
                    "error": {
                        "code": "PROVIDER_UNAVAILABLE",
                        "message": "Unavailable",
                        "retryable": True,
                    },
                    "correlation_id": "mcp-test",
                    "source": "student-4",
                }
            result = {
                "content": [{"type": "text", "text": json.dumps(envelope)}],
                "structuredContent": envelope,
                "isError": self.fail,
            }
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
        )


def run(actions: list[dict[str, Any]], mcp: ProtocolFake) -> dict[str, Any]:
    def ai(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "activities_delete" not in body["prompt"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "test",
                    "model": "test",
                    "provider": "ollama",
                    "done": True,
                    "response": json.dumps(actions.pop(0)),
                }
            },
        )

    settings = Settings(
        ai_mode_url="http://ai.test", mcp_enabled=True, mcp_url="http://mcp.test/mcp"
    )
    with TestClient(
        create_app(
            settings,
            ai_mode_transport=httpx.MockTransport(ai),
            mcp_transport=httpx.MockTransport(mcp.handle),
        )
    ) as client:
        response = client.post("/activity/assistant", json={"question": "Find walks"})
        assert response.status_code == 200, response.text
        return dict(response.json())


def test_agent_calls_mcp_and_returns_authoritative_cards_and_trace() -> None:
    mcp = ProtocolFake()
    result = run(
        [
            {
                "type": "tool",
                "name": "activities_search",
                "arguments": {"text": "walk"},
            },
            {
                "type": "final",
                "parts": [
                    {"type": "text", "text": "Try this"},
                    {"type": "activity", "activity_id": ACTIVITY},
                ],
            },
        ],
        mcp,
    )
    assert result["status"] == "complete"
    assert result["activities"][ACTIVITY]["price"] == "45.00"
    assert [call["name"] for call in mcp.calls] == [
        "activities_search",
        "activities_get",
    ]
    assert [entry["tool"] for entry in result["tools"]] == [
        "activities_search",
        "activities_get",
    ]
    assert all(entry["status"] == "success" for entry in result["tools"])
    assert result["tools"][0]["correlation_id"] == "mcp-test"


def test_write_tool_is_rejected_without_execution() -> None:
    mcp = ProtocolFake()
    result = run(
        [
            {
                "type": "tool",
                "name": "activities_delete",
                "arguments": {"activity_id": ACTIVITY},
            }
        ],
        mcp,
    )
    assert result["status"] == "error"
    assert mcp.calls == []


def test_unknown_activity_reference_cannot_become_a_card() -> None:
    mcp = ProtocolFake()
    result = run(
        [{"type": "final", "parts": [{"type": "activity", "activity_id": ACTIVITY}]}],
        mcp,
    )
    assert result["status"] == "error"
    assert result["activities"] == {}
    assert mcp.calls == []


def test_trip_read_requires_selected_trip() -> None:
    mcp = ProtocolFake()
    result = run(
        [
            {
                "type": "tool",
                "name": "trip_get_context",
                "arguments": {"trip_id": "trip_someone_else"},
            }
        ],
        mcp,
    )
    assert result["status"] == "error"
    assert mcp.calls == []


def test_failed_tool_is_shown_in_trace() -> None:
    mcp = ProtocolFake()
    mcp.fail = True
    result = run(
        [
            {"type": "tool", "name": "activities_search", "arguments": {}},
            {
                "type": "final",
                "parts": [{"type": "text", "text": "The catalogue is unavailable."}],
            },
        ],
        mcp,
    )
    assert result["tools"][0]["status"] == "error"
    assert result["tools"][0]["error"] == "PROVIDER_UNAVAILABLE"


def test_generation_schema_restricts_tool_names_and_arguments() -> None:
    from jsonschema import Draft202012Validator
    from mcp.types import Tool
    from student4_backend_service.assistant_schema import action_schema

    schema = action_schema(
        [
            Tool(
                name="activities_get",
                inputSchema={
                    "type": "object",
                    "properties": {"activity_id": {"type": "string"}},
                    "required": ["activity_id"],
                    "additionalProperties": False,
                },
            )
        ]
    )
    validator = Draft202012Validator(schema)
    assert validator.is_valid(
        {
            "type": "tool",
            "name": "activities_get",
            "arguments": {"activity_id": ACTIVITY},
        }
    )
    assert not validator.is_valid(
        {"type": "tool", "name": "activities_delete", "arguments": {}}
    )
    assert not validator.is_valid(
        {"type": "tool", "name": "activities_get", "arguments": {"url": "http://evil"}}
    )


def test_each_request_starts_with_no_known_activity_ids() -> None:
    mcp = ProtocolFake()
    run(
        [
            {"type": "tool", "name": "activities_search", "arguments": {}},
            {"type": "final", "parts": [{"type": "activity", "activity_id": ACTIVITY}]},
        ],
        mcp,
    )
    second = run(
        [{"type": "final", "parts": [{"type": "activity", "activity_id": ACTIVITY}]}],
        mcp,
    )
    assert second["status"] == "error"
    assert second["tools"] == []


def test_agent_stops_repeated_tool_calls_at_step_limit() -> None:
    from student4_backend_service.assistant import MAX_STEPS

    mcp = ProtocolFake()
    result = run(
        [
            {"type": "tool", "name": "activities_search", "arguments": {}}
            for _ in range(MAX_STEPS)
        ],
        mcp,
    )
    assert result["status"] == "error"
    assert len(mcp.calls) <= MAX_STEPS
    assert "limit" in result["error"] or "context" in result["error"]


def test_disabled_mcp_never_calls_network() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    with TestClient(
        create_app(Settings(), mcp_transport=httpx.MockTransport(unexpected))
    ) as client:
        response = client.post("/activity/assistant", json={"question": "Walks"})
    assert response.status_code == 200
    assert "disabled" in response.json()["error"]
    assert response.json()["tools"] == []


def test_wrong_provider_activity_id_is_never_rendered() -> None:
    class WrongId(ProtocolFake):
        def handle(self, request: httpx.Request) -> httpx.Response:
            response = super().handle(request)
            body = json.loads(request.content)
            if (
                body.get("method") == "tools/call"
                and body["params"]["name"] == "activities_get"
            ):
                data = response.json()
                data["result"]["structuredContent"]["data"]["id"] = (
                    "11111111-1111-1111-1111-111111111111"
                )
                return httpx.Response(200, json=data)
            return response

    result = run(
        [
            {"type": "tool", "name": "activities_search", "arguments": {}},
            {"type": "final", "parts": [{"type": "activity", "activity_id": ACTIVITY}]},
        ],
        WrongId(),
    )
    assert result["status"] == "error"
    assert result["activities"] == {}
    assert result["tools"][-1]["status"] == "error"


def test_invalid_tool_arguments_never_reach_mcp() -> None:
    mcp = ProtocolFake()
    result = run(
        [
            {
                "type": "tool",
                "name": "activities_search",
                "arguments": {"url": "http://other"},
            }
        ],
        mcp,
    )
    assert result["status"] == "error"
    assert result["tools"][0]["status"] == "rejected"
    assert mcp.calls == []


def test_deadline_terminates_model_work_without_fallback() -> None:
    import asyncio

    async def slow_ai(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(500)

    mcp = ProtocolFake()
    settings = Settings(
        ai_mode_url="http://ai.test",
        mcp_enabled=True,
        mcp_url="http://mcp.test/mcp",
        agent_timeout=0.05,
    )
    with TestClient(
        create_app(
            settings,
            ai_mode_transport=httpx.MockTransport(slow_ai),
            mcp_transport=httpx.MockTransport(mcp.handle),
        )
    ) as client:
        response = client.post("/activity/assistant", json={"question": "Walks"})
    assert response.json()["status"] == "error"
    assert "timed out" in response.json()["error"]
    assert mcp.calls == []


def test_mcp_transport_failure_is_visible_and_does_not_fallback() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        message = "private upstream address"
        raise httpx.ConnectError(message, request=request)

    settings = Settings(
        ai_mode_url="http://ai.test", mcp_enabled=True, mcp_url="http://mcp.test/mcp"
    )
    with TestClient(
        create_app(settings, mcp_transport=httpx.MockTransport(offline))
    ) as client:
        response = client.post("/activity/assistant", json={"question": "Walks"})
    assert response.json()["status"] == "error"
    assert "unavailable" in response.json()["error"]
    assert "private upstream" not in response.text
    assert response.json()["tools"] == []


def test_duplicate_activity_parts_cannot_exceed_card_limit() -> None:
    mcp = ProtocolFake()
    result = run(
        [
            {"type": "tool", "name": "activities_search", "arguments": {}},
            {
                "type": "final",
                "parts": [{"type": "activity", "activity_id": ACTIVITY}] * 12,
            },
        ],
        mcp,
    )
    assert result["status"] == "error"
    assert result["parts"] == []
    assert len(mcp.calls) == 1
