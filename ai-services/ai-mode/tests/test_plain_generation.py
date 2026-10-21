"""/generate-plain makes one model call and never executes an MCP tool."""

import json

import httpx
from fastapi.testclient import TestClient
from test_agent import MCP, message

from ai_mode_service.app import create_app
from ai_mode_service.config import Settings

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def run(responses, request_payload=None, **settings):
    mcp = MCP()
    requests = []

    def model(request):
        assert request.url.path == "/api/chat"
        requests.append(json.loads(request.content))
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def unreachable_mcp(request):
        mcp.handle(request)
        raise AssertionError("plain generation must not contact MCP")

    app = create_app(
        Settings(default_model="llama3.1:8b", **settings),
        ollama_transport=httpx.MockTransport(model),
        mcp_transport=httpx.MockTransport(unreachable_mcp),
    )
    with TestClient(app) as client:
        response = client.post(
            "/generate-plain",
            json={
                "system": "trusted instructions",
                "prompt": "Answer from the supplied context only",
                **(request_payload or {}),
            },
        )
    return response, requests


def test_single_tool_free_call_returns_schema_valid_answer():
    response, requests = run(
        [message('{"answer": "Bring a hat."}')], {"schema": SCHEMA}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert json.loads(data["response"]) == {"answer": "Bring a hat."}
    assert data["tools"] == []
    assert len(requests) == 1
    assert requests[0]["tools"] == []
    assert requests[0]["format"]["required"] == ["answer"]
    assert requests[0]["messages"] == [
        {"role": "system", "content": "trusted instructions"},
        {"role": "user", "content": "Answer from the supplied context only"},
    ]


def test_plain_text_without_schema_is_returned():
    response, requests = run([message("Plain answer")])

    assert response.status_code == 200, response.text
    assert response.json()["data"]["response"] == "Plain answer"
    assert requests[0]["format"] is None


def test_provider_timeout_is_reported_as_timeout_without_tool_trace():
    response, _ = run([httpx.ReadTimeout("slow")])

    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_TIMEOUT"
    assert "tools" not in body


def test_invalid_structured_answer_is_rejected():
    response, _ = run([message("not json")], {"schema": SCHEMA})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BAD_GATEWAY"


def test_unexpected_tool_request_is_rejected():
    response, _ = run([message(name="activities_search", arguments={"value": "x"})])

    assert response.status_code == 502


def test_empty_answer_is_rejected():
    response, _ = run([message("   ")])

    assert response.status_code == 502


def run_with_catalogue(
    responses, request_payload=None, mcp=None, path="/generate-plain"
):
    mcp = mcp or MCP()
    requests = []

    def model(request):
        requests.append(json.loads(request.content))
        return responses.pop(0)

    app = create_app(
        Settings(default_model="llama3.1:8b"),
        ollama_transport=httpx.MockTransport(model),
        mcp_transport=httpx.MockTransport(mcp.handle),
    )
    with TestClient(app) as client:
        response = client.post(
            path,
            json={
                "system": "trusted instructions",
                "prompt": "Plan this task",
                "tool_catalogue": True,
                **(request_payload or {}),
            },
        )
    return response, requests, mcp


def test_tool_catalogue_describes_every_tool_without_executing_any():
    response, requests, mcp = run_with_catalogue(
        [message('{"answer": "Plan."}')], {"schema": SCHEMA}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["tools"] == []
    assert mcp.calls == []
    assert len(requests) == 1
    # Never offered as callable functions, so the call stays schema-constrained.
    assert requests[0]["tools"] == []
    assert requests[0]["format"]["required"] == ["answer"]
    system, user = requests[0]["messages"]
    assert user == {"role": "user", "content": "Plan this task"}
    assert system["role"] == "system"
    assert system["content"].startswith("trusted instructions\n\n")
    catalogue = json.loads(system["content"].split("\n")[-1])
    # The same native definitions /generate sends, across both MCP pages.
    assert catalogue == [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            },
        }
        for tool in mcp.tools
    ]


def test_tool_catalogue_needs_mcp_and_reports_it_unavailable():
    class DownMCP(MCP):
        def handle(self, request):
            raise httpx.ConnectError("refused")

    response, requests, _ = run_with_catalogue([], mcp=DownMCP())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert requests == []


def test_tool_catalogue_is_rejected_on_the_tool_loop_endpoint():
    response, requests, mcp = run_with_catalogue([], path="/generate")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "tool_catalogue"
    assert requests == []
    assert mcp.calls == []
