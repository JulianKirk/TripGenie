"""The shared endpoint executes model-selected MCP tools without domain parsing."""

import json

import httpx
from fastapi.testclient import TestClient

from ai_mode_service.app import create_app
from ai_mode_service.config import Settings


class MCP:
    def __init__(self):
        self.calls = []
        self.tools = [
            {
                "name": name,
                "description": f"Published description of {name}",
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            }
            for name in (
                "activities_search",
                "budgets_get_summary",
                "activities_delete",
            )
        ]

    def handle(self, request):
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1"},
            }
        elif body["method"] == "tools/list":
            cursor = body.get("params", {}).get("cursor")
            result = (
                {"tools": self.tools[1:]}
                if cursor
                else {"tools": self.tools[:1], "nextCursor": "next"}
            )
        else:
            assert body["method"] == "tools/call"
            self.calls.append(body["params"])
            result = {
                "content": [{"type": "text", "text": "actual result"}],
                "structuredContent": {"ok": True, "data": {"value": "actual result"}},
                "isError": False,
            }
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
        )


def message(content="", name=None, arguments=None, done_reason="stop"):
    result = {"role": "assistant", "content": content}
    if name:
        result["tool_calls"] = [{"function": {"name": name, "arguments": arguments}}]
    return httpx.Response(
        200,
        json={
            "model": "llama3.1:8b",
            "message": result,
            "done": True,
            "done_reason": done_reason,
        },
    )


def run(responses, mcp=None, request_payload=None, **settings):
    mcp = mcp or MCP()
    requests = []

    def model(request):
        assert request.url.path == "/api/chat"
        requests.append(json.loads(request.content))
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    app = create_app(
        Settings(default_model="llama3.1:8b", **settings),
        ollama_transport=httpx.MockTransport(model),
        mcp_transport=httpx.MockTransport(mcp.handle),
    )
    with TestClient(app) as client:
        response = client.post(
            "/generate",
            json={
                "system": "trusted instructions",
                "prompt": "Next Friday, under twenty dollars for everyone",
                **(request_payload or {}),
            },
        )
    return response, requests, mcp


def test_all_discovered_tools_and_verbatim_arguments_reach_shared_loop():
    responses = [
        message(name="budgets_get_summary", arguments={"value": "unaltered"}),
        message(name="activities_delete", arguments={"value": "chosen by model"}),
        message("Model authored answer"),
    ]
    response, requests, mcp = run(responses)
    assert response.status_code == 200, response.text
    assert {tool["function"]["name"] for tool in requests[0]["tools"]} == {
        tool["name"] for tool in mcp.tools
    }
    assert (
        requests[0]["tools"][0]["function"]["description"]
        == mcp.tools[0]["description"]
    )
    assert requests[0]["messages"][0] == {
        "role": "system",
        "content": "trusted instructions",
    }
    assert (
        requests[0]["messages"][1]["content"]
        == "Next Friday, under twenty dollars for everyone"
    )
    assert [call["arguments"] for call in mcp.calls] == [
        {"value": "unaltered"},
        {"value": "chosen by model"},
    ]
    assert any(
        item["role"] == "tool" and "actual result" in item["content"]
        for item in requests[1]["messages"]
    )
    assert response.json()["data"]["response"] == "Model authored answer"
    assert len(response.json()["data"]["tools"]) == 2


def test_complete_mcp_schemas_reach_ollama_on_every_tool_round():
    mcp = MCP()
    schema = mcp.tools[0]["inputSchema"]
    schema["$defs"] = {
        "Filter": {
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 1}},
            "additionalProperties": False,
        }
    }
    schema["properties"]["filters"] = {
        "anyOf": [{"$ref": "#/$defs/Filter"}, {"type": "null"}],
        "default": None,
    }
    response, requests, _ = run(
        [
            message(name="activities_search", arguments={"value": "first"}),
            message(name="budgets_get_summary", arguments={"value": "second"}),
            message("Done"),
        ],
        mcp=mcp,
    )
    assert response.status_code == 200
    for request in requests:
        advertised = {t["function"]["name"]: t["function"] for t in request["tools"]}
        for tool in mcp.tools:
            assert advertised[tool["name"]]["parameters"] == tool["inputSchema"]


def test_unknown_tool_and_invalid_arguments_never_execute():
    for name, arguments in [
        ("invented", {"value": "x"}),
        ("activities_delete", {"wrong": 1}),
    ]:
        response, _, mcp = run([message(name=name, arguments=arguments)])
        assert response.status_code == 502
        assert not mcp.calls
        assert response.json()["tools"][0]["status"] == "rejected"


def test_partial_trace_survives_provider_failure_without_replaying_write():
    response, _, mcp = run(
        [
            message(name="activities_delete", arguments={"value": "x"}),
            httpx.ReadTimeout("test timeout"),
        ]
    )
    assert response.status_code == 504
    assert len(mcp.calls) == 1
    assert response.json()["tools"][0]["status"] == "success"


def test_identical_call_is_not_executed_twice():
    response, _, mcp = run(
        [
            message(name="activities_delete", arguments={"value": "x"}),
            message(name="activities_delete", arguments={"value": "x"}),
        ]
    )
    assert response.status_code == 502
    assert len(mcp.calls) == 1


def test_context_limit_fails_without_silently_hiding_tools():
    response, requests, mcp = run([], agent_context_chars=1)
    assert response.status_code == 502
    assert "context" in response.json()["error"]["message"]
    assert not requests and not mcp.calls


def test_call_and_turn_limits_stop_execution():
    response, _, mcp = run(
        [
            message(name="activities_search", arguments={"value": "a"}),
            message(name="activities_search", arguments={"value": "b"}),
        ],
        agent_max_calls=1,
    )
    assert response.status_code == 502
    assert len(mcp.calls) == 1
    response, _, mcp = run(
        [message(name="activities_search", arguments={"value": "a"})], agent_max_turns=1
    )
    assert response.status_code == 502
    assert len(mcp.calls) == 1
    assert response.json()["tools"][0]["status"] == "success"


def test_oversized_tool_result_omits_data_but_retains_execution_status():
    response, _, mcp = run(
        [message(name="activities_search", arguments={"value": "a"})],
        agent_result_bytes=5,
    )
    assert response.status_code == 502
    assert len(mcp.calls) == 1
    assert response.json()["tools"][0]["status"] == "success"
    assert response.json()["tools"][0]["error"] == "RESULT_TOO_LARGE"
    assert response.json()["tools"][0]["result"] is None


def test_mcp_failure_prevents_unassisted_generation():
    mcp = MCP()

    def unavailable(request):
        raise httpx.ConnectError("offline")

    mcp.handle = unavailable
    response, requests, _ = run([], mcp=mcp)
    assert response.status_code == 503
    assert not requests


def test_read_after_write_can_refresh_the_same_query():
    mcp = MCP()
    mcp.tools[0]["annotations"] = {"readOnlyHint": True}
    response, _, mcp = run(
        [
            message(name="activities_search", arguments={"value": "same"}),
            message(name="activities_delete", arguments={"value": "x"}),
            message(name="activities_search", arguments={"value": "same"}),
            message("Verified the change"),
        ],
        mcp=mcp,
    )
    assert response.status_code == 200, response.text
    assert len(mcp.calls) == 3


def test_oversized_successful_write_is_reported_as_completed():
    response, _, _ = run(
        [message(name="activities_delete", arguments={"value": "x"})],
        agent_result_bytes=5,
    )
    assert response.status_code == 502
    assert response.json()["tools"][0]["status"] == "success"
    assert response.json()["tools"][0]["error"] == "RESULT_TOO_LARGE"


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def test_preamble_gets_a_tool_enabled_check_before_final_formatting():
    response, requests, mcp = run(
        [
            message("Here are some activities:"),
            message(name="activities_search", arguments={"value": "kayak"}),
            message("The search returned an activity."),
            message('{"answer":"The search returned an activity."}'),
        ],
        request_payload={"schema": ANSWER_SCHEMA},
    )
    assert response.status_code == 200, response.text
    assert len(mcp.calls) == 1
    assert requests[1]["tools"] == requests[0]["tools"]
    assert requests[1]["format"] is None
    assert requests[-1]["tools"] == []
    assert requests[-1]["format"] == ANSWER_SCHEMA


def test_tool_free_clarification_is_checked_once_then_formatted():
    response, requests, mcp = run(
        [
            message("How many people?"),
            message("How many people?"),
            message('{"answer":"How many people?"}'),
        ],
        request_payload={"schema": ANSWER_SCHEMA},
    )
    assert response.status_code == 200, response.text
    assert len(requests) == 3
    assert not mcp.calls
    assert response.json()["data"]["response"] == '{"answer":"How many people?"}'


def test_truncated_response_is_rejected_before_any_tool_execution():
    response, _, mcp = run(
        [
            message(
                name="activities_delete", arguments={"value": "x"}, done_reason="length"
            )
        ]
    )
    assert response.status_code == 502
    assert "truncated" in response.json()["error"]["message"]
    assert not mcp.calls


def test_truncated_answer_preserves_prior_write_trace_without_retry():
    response, requests, mcp = run(
        [
            message(name="activities_delete", arguments={"value": "x"}),
            message("I have", done_reason="length"),
        ]
    )
    assert response.status_code == 502
    assert len(requests) == 2
    assert len(mcp.calls) == 1
    assert response.json()["tools"][0]["status"] == "success"
