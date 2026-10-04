"""The assistant box: AI-Mode (and the MCP loop behind it) is a MockTransport.

The trace AI-Mode returns is the evidence a tool ran, so the assertions are
that each call's tool, arguments and returned data reach the response -- also
when the run fails part way.
"""

from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import Settings

AI_MODE_URL = "http://ai-mode.test"
LISTING = {"id": "0b6c...", "name": "Harbour Hotel", "price_per_night": "180.00"}
SEARCH_TRACE = {
    "tool": "accommodations_search",
    "arguments": {"country": "Australia", "city": "Sydney", "limit": 5},
    "status": "success",
    "duration_ms": 42,
    "result": {
        "content": [],
        "isError": False,
        "structuredContent": {
            "ok": True,
            "data": {"items": [LISTING], "count": 1, "truncated": False},
            "correlation_id": "mcp-1",
            "source": "student-2",
        },
    },
}
FAILED_TRACE = {
    "tool": "accommodations_get",
    "arguments": {"accommodation_id": "nope"},
    "status": "error",
    "duration_ms": 3,
    "result": {
        "isError": True,
        "structuredContent": {
            "ok": False,
            "error": {"code": "VALIDATION_ERROR", "message": "bad id"},
            "source": "student-2",
        },
    },
    "error": "TOOL_ERROR",
}


def ask(handler, *, ai_mode_url=AI_MODE_URL):
    sent = []

    def recording(request):
        sent.append(json.loads(request.content))
        return handler(request)

    app = create_app(
        Settings(ai_mode_url=ai_mode_url),
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
        ai_transport=httpx.MockTransport(recording),
    )
    with TestClient(app) as client:
        response = client.post(
            "/accommodation/assistant", json={"question": "Stays in Sydney?"}
        )
    return response, sent


def generated(reply, tools):
    return httpx.Response(
        200, json={"data": {"response": reply, "tools": tools, "done": True}}
    )


def test_tool_calls_and_their_data_are_returned():
    response, sent = ask(
        lambda _: generated("Harbour Hotel, 180 a night.", [SEARCH_TRACE])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["reply"] == "Harbour Hotel, 180 a night."
    [call] = body["tools"]
    assert call["tool"] == "accommodations_search"
    assert call["arguments"]["city"] == "Sydney"
    assert call["source"] == "student-2"
    assert call["data"]["items"] == [LISTING]
    # The question goes as the prompt, the packaged prompt as the system turn,
    # and no schema: the reply is free text.
    assert sent[0]["prompt"] == "Stays in Sydney?"
    assert "accommodations_search" in sent[0]["system"]
    assert "schema" not in sent[0]


def test_a_failed_tool_says_why_and_carries_no_data():
    body = ask(lambda _: generated("That id is not valid.", [FAILED_TRACE]))[0].json()
    [call] = body["tools"]
    assert call["status"] == "error"
    assert call["data"] is None
    assert call["error"] == "VALIDATION_ERROR bad id"


def test_a_failed_run_keeps_the_tools_that_ran():
    failed = httpx.Response(
        502,
        json={
            "error": {"code": "BAD_GATEWAY", "message": "model gave up", "details": []},
            "tools": [SEARCH_TRACE],
        },
    )
    body = ask(lambda _: failed)[0].json()
    assert body["status"] == "error"
    assert body["error"] == "model gave up"
    assert body["tools"][0]["data"]["count"] == 1


def test_unset_ai_mode_url_is_disabled_and_sends_nothing():
    response, sent = ask(lambda _: generated("x", []), ai_mode_url=None)
    assert response.json()["status"] == "disabled"
    assert sent == []


def test_an_unreachable_ai_mode_is_an_error_status():
    def down(request):
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    body = ask(down)[0].json()
    assert body["status"] == "error"
    assert body["tools"] == []
