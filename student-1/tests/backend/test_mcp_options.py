from __future__ import annotations

import json

import httpx
import pytest
from backend_service.config import Settings
from backend_service.prompt_assets import load_prompt_asset
from backend_service.service import MCP_FINAL_ANSWER_SCHEMA
from conftest import create_trip_payload

ENABLED = Settings(
    database_api_base_url="http://database.test",
    ai_mode_base_url="http://ai-mode.test",
    mcp_enabled=True,
    mcp_timeout_seconds=200,
)
STAY_ID = "6f1c2a52-1111-4b5e-9a0a-000000000001"
BUDGET_ID = "6f1c2a52-2222-4b5e-9a0a-000000000002"


def trace(tool: str, data: dict | None, status: str = "success", **extra) -> dict:
    result = None
    if data is not None:
        result = {
            "content": [],
            "structuredContent": {
                "ok": True,
                "data": data,
                "correlation_id": "c",
                "source": "x",
            },
            "isError": False,
        }
    return {
        "tool": tool,
        "arguments": extra.pop("arguments", {"limit": 5}),
        "status": status,
        "duration_ms": 12,
        "result": result,
        "error": extra.pop("error", None),
    }


def trip_trace(trip_id: str) -> dict:
    return trace("trip_get_context", {"id": trip_id}, arguments={"trip_id": trip_id})


def answer(*options: dict, summary: str = "Two good fits.") -> str:
    return json.dumps({"summary": summary, "options": list(options)})


def option(category: str, name: str, id_: str | None) -> dict:
    return {"category": category, "name": name, "detail": "fits", "id": id_}


def generated(tools: list[dict], response: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "run_id": "run_1",
                "correlation_id": "student1-mcp-abc",
                "model": "qwen3:8b",
                "provider": "ollama",
                "response": response,
                "done": True,
                "tools": tools,
            }
        },
    )


class FakeAiMode:
    """Answers each /generate with the next canned reply (a callable gets trip_id)."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.bodies: list[dict] = []
        self.timeouts: list[float] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/generate":
            raise AssertionError(f"unexpected AI-Mode call {request.url}")
        body = json.loads(request.content)
        self.bodies.append(body)
        self.timeouts.append(request.extensions["timeout"]["read"])
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(json.loads(body["prompt"])["trip"]["id"])
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def make(client_factory, database_api):
    def _make(*replies, settings=ENABLED):
        ai = FakeAiMode(*replies)
        client = client_factory(
            database_api.handle, settings_override=settings, ai_mode_handler=ai.handle
        )
        return client, ai

    return _make


def _run(client, destination="Sydney, Australia", body: object = None):
    trip = client.post("/api/trips", json=create_trip_payload(destination=destination))
    trip_id = trip.json()["data"]["id"]
    kwargs = {} if body is None else {"json": body}
    return trip_id, client.post(f"/api/trips/{trip_id}/mcp-options", **kwargs)


def full_run(trip_id: str) -> httpx.Response:
    return generated(
        [
            trip_trace(trip_id),
            trace("accommodations_search", {"items": [{"id": STAY_ID, "name": "H"}]}),
            trace("budgets_list", {"budgets": [{"budget_id": BUDGET_ID}]}),
            trace("transport_search", None, status="error", error="provider down"),
        ],
        answer(
            option("accommodation", "Harbour Hotel", STAY_ID),
            option("budget", "Trip budget", BUDGET_ID),
            option("activity", "Invented tour", "made-up-id"),
            option("transport", "Some ferry", None),
        ),
    )


def test_model_drives_tools_and_answer_is_grounded(make) -> None:
    client, ai = make(full_run)
    with client:
        trip_id, response = _run(
            client, "Canberra", {"request": "Find a stay", "country": " Australia "}
        )

    assert response.status_code == 200
    # What AI-Mode was asked: system prompt, schema, trip context, metadata.
    (body,) = ai.bodies
    assert body["system"] == load_prompt_asset("trip_tools_assistant_v1.md")
    assert body["schema"] == MCP_FINAL_ANSWER_SCHEMA
    prompt = json.loads(body["prompt"])
    assert prompt["request"] == "Find a stay"
    assert prompt["trip"]["id"] == trip_id
    assert prompt["trip"]["city"] == "Canberra"
    assert prompt["trip"]["country"] == "Australia"
    assert prompt["trip"]["traveller_count"] == 2
    assert body["metadata"]["service"] == "student-1-backend"
    assert body["metadata"]["feature"] == "trip-tools-assistant"
    assert body["metadata"]["trip_id"] == trip_id
    assert body["correlation_id"].startswith("student1-mcp-")
    assert 190 < ai.timeouts[0] <= 200

    data = response.json()["data"]
    assert data["persisted"] is False
    assert data["run_id"] == "run_1" and data["model"] == "qwen3:8b"
    assert data["location"] == {"city": "Canberra", "country": "Australia"}
    assert data["summary"] == "Two good fits."
    # The unknown id and the null-id "Some ferry" are both dropped.
    assert [(o["name"], o["source_tool"]) for o in data["options"]] == [
        ("Harbour Hotel", "accommodations_search"),
        ("Trip budget", "budgets_list"),
    ]
    assert data["ungrounded_dropped"] == 2
    assert data["write_tools_called"] == []
    assert data["tool_summary"] == {"success": 3, "error": 1, "rejected": 0}
    assert data["tools"][0] == {
        "tool": "trip_get_context",
        "arguments": {"trip_id": trip_id},
        "status": "success",
        "duration_ms": 12,
        "data": {"id": trip_id},
        "error": None,
    }
    assert data["tools"][3]["error"] == "provider down"
    assert data["tools"][3]["data"] is None


def test_defaults_and_destination_country(make) -> None:
    client, ai = make(full_run)
    with client:
        _, response = _run(client, body={})

    assert response.status_code == 200
    prompt = json.loads(ai.bodies[0]["prompt"])
    assert prompt["request"].startswith("Find accommodation, activities and transport")
    assert prompt["trip"]["country"] == "Australia"
    assert prompt["trip"]["city"] == "Sydney"


def test_write_tools_are_reported(make) -> None:
    def run(trip_id: str) -> httpx.Response:
        return generated(
            [
                trip_trace(trip_id),
                trace("activities_create", {"id": "new"}),
                trace("activities_delete", None, status="rejected", error="no"),
            ],
            answer(),
        )

    client, _ = make(run)
    with client:
        _, response = _run(client)

    data = response.json()["data"]
    assert data["write_tools_called"] == ["activities_create", "activities_delete"]
    assert data["tool_summary"] == {"success": 2, "error": 0, "rejected": 1}
    assert data["persisted"] is False


def test_no_tool_use_is_retried_once_then_fails(make) -> None:
    lazy = generated([], answer(option("accommodation", "Memory Inn", "x")))
    failed = generated([trace("trip_get_context", None, "error", error="boom")], "{}")
    client, ai = make(lazy, failed)
    with client:
        _, response = _run(client)

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "MCP_TOOLS_NOT_USED"
    assert error["details"] == [{"field": "trip_get_context", "issue": "boom"}]
    assert [b["metadata"]["attempt"] for b in ai.bodies] == ["1", "2"]


def test_retry_that_uses_tools_succeeds(make) -> None:
    client, ai = make(generated([], answer()), full_run)
    with client:
        _, response = _run(client)

    assert response.status_code == 200
    assert len(ai.bodies) == 2
    assert response.json()["data"]["tool_summary"]["success"] == 3


@pytest.mark.parametrize(
    ("reply", "status", "code"),
    [
        (
            httpx.Response(
                503,
                json={"error": {"code": "DEPENDENCY_UNAVAILABLE", "message": "down"}},
            ),
            503,
            "DEPENDENCY_UNAVAILABLE",
        ),
        (httpx.ReadTimeout("slow"), 504, "DEPENDENCY_TIMEOUT"),
        (httpx.Response(200, text="nope"), 502, "BAD_GATEWAY"),
        (
            lambda trip_id: generated(
                [{"tool": "x", "arguments": {}, "status": "weird"}], answer()
            ),
            502,
            "BAD_GATEWAY",
        ),
        (
            lambda trip_id: generated([trip_trace(trip_id)], "not json"),
            502,
            "AI_OUTPUT_INVALID",
        ),
    ],
)
def test_ai_mode_failures_propagate(make, reply, status, code) -> None:
    client, _ = make(reply)
    with client:
        _, response = _run(client)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_disabled_is_an_explicit_error(make) -> None:
    settings = Settings(
        database_api_base_url="http://database.test",
        ai_mode_base_url="http://ai-mode.test",
    )
    client, ai = make(settings=settings)
    with client:
        _, response = _run(client, body={})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MCP_DISABLED"
    assert ai.bodies == []


def test_ai_mode_not_configured_is_an_explicit_error(client_factory, database_api):
    settings = Settings(database_api_base_url="http://database.test", mcp_enabled=True)
    with client_factory(database_api.handle, settings_override=settings) as client:
        _, response = _run(client)

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DEPENDENCY_UNAVAILABLE"
    assert error["details"][0]["field"] == "ai_mode"


def test_unknown_trip_is_404_without_calling_ai_mode(make) -> None:
    client, ai = make()
    with client:
        response = client.post("/api/trips/trip_missing/mcp-options")

    assert response.status_code == 404
    assert ai.bodies == []


@pytest.mark.parametrize(
    "body",
    [
        {"country": "  "},
        {"country": "x" * 101},
        {"request": "x" * 501},
        {"request": " "},
        {"k": 1},
    ],
)
def test_invalid_body_is_rejected(make, body) -> None:
    client, ai = make()
    with client:
        _, response = _run(client, "Canberra", body)

    assert response.status_code == 422
    assert ai.bodies == []


def test_ready_does_not_call_ai_mode(make) -> None:
    client, ai = make()
    with client:
        ready = client.get("/ready")

    assert ready.status_code == 200
    assert ai.bodies == []
