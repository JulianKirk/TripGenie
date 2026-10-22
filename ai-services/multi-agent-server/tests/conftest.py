"""Fixtures: the real server with a fake AI-Mode behind an injected transport.

The fake answers `/generate-plain` for the Planner and Reviewer and
`/generate` for the Worker, keyed on the `agent` metadata the server sends,
and records every request so tests can assert what each agent was given.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastapi.testclient import TestClient
from multi_agent_service.app import create_app
from multi_agent_service.config import Settings

if TYPE_CHECKING:
    from pathlib import Path

TRANSPORT_A = "transport_2026_qf401_mel_syd"
TRANSPORT_B = "transport_2026_spirit_geelong_devonport"

PLAN = {
    "goal": "Find the cheapest transport for four travellers to Tasmania.",
    "steps": [
        "Call transport_search with destination Devonport.",
        "Compare prices for four travellers and pick the cheapest.",
    ],
    "required_evidence": ["transport prices from transport_search"],
    "tools_to_use": ["transport_search", "activities_delete"],
    "success_criteria": ["every suggested id appears in a tool result"],
}

WORKER_RESULT = {
    "answer": "The Spirit of Tasmania ferry is the only option found.",
    "items": [{"id": TRANSPORT_B, "reason": "Only Geelong to Devonport route."}],
    "actions": [
        {"type": "add_to_trip", "transport_id": TRANSPORT_B, "travellers": 4},
        {"type": "note", "text": "Book a cabin early."},
    ],
}

APPROVE = {
    "verdict": "approve",
    "summary": "Supported by transport_search.",
    "issues": [],
    "risks": ["Availability may change before travel."],
    "recommendations": ["Confirm seats before adding to the trip."],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "items", "actions"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "reason"],
                "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
        "actions": {"type": "array", "items": {"type": "object"}},
    },
}


def tool_trace(
    tool: str = "transport_search",
    ids: tuple[str, ...] = (TRANSPORT_B,),
    *,
    status: str = "success",
    source: str = "student-3",
) -> dict[str, Any]:
    return {
        "tool": tool,
        "arguments": {"destination": "Devonport", "limit": 5},
        "status": status,
        "duration_ms": 21,
        "result": {
            "content": [],
            "structuredContent": {
                "ok": status == "success",
                "data": {"items": [{"id": value, "price": "289.00"} for value in ids]},
                "source": source,
            },
            "isError": status != "success",
        },
        "error": None if status == "success" else "TOOL_ERROR",
    }


def generation(body: Any, tools: list[dict[str, Any]] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "run_id": "aimode_000000000001",
                "correlation_id": "c",
                "model": "llama3.1:8b",
                "provider": "ollama",
                "response": body if isinstance(body, str) else json.dumps(body),
                "done": True,
                "tools": tools or [],
                "available_tools": ["transport_search", "transport_get"],
            },
        },
    )


def ai_error(status: int, code: str, tools: list | None = None) -> httpx.Response:
    body: dict[str, Any] = {
        "error": {"code": code, "message": f"AI-Mode said {code}", "details": []},
    }
    if tools:
        body["tools"] = tools
    return httpx.Response(status, json=body)


Reply = Callable[[dict[str, Any]], httpx.Response]


@dataclass
class FakeAiMode:
    """AI-Mode as the server sees it. Each agent gets a queue of replies."""

    planner: list[Reply] = field(default_factory=list)
    worker: list[Reply] = field(default_factory=list)
    reviewer: list[Reply] = field(default_factory=list)
    health_status: str = "ok"
    reachable: bool = True
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.planner = self.planner or [lambda _: generation(PLAN)]
        self.worker = self.worker or [
            lambda _: generation(WORKER_RESULT, [tool_trace()])
        ]
        self.reviewer = self.reviewer or [lambda _: generation(APPROVE)]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            message = "connection refused"
            raise httpx.ConnectError(message, request=request)
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"data": {"status": self.health_status, "service": "ai-mode"}},
            )
        body = json.loads(request.content)
        agent = body["metadata"]["agent"]
        self.calls.append({"path": request.url.path, "agent": agent, "body": body})
        queue: list[Reply] = getattr(self, agent)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return reply(body)

    def bodies(self, agent: str) -> list[dict[str, Any]]:
        return [call["body"] for call in self.calls if call["agent"] == agent]


@pytest.fixture
def fake() -> FakeAiMode:
    return FakeAiMode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "runs.sqlite3")


@pytest.fixture
def client(settings: Settings, fake: FakeAiMode) -> Iterator[TestClient]:
    app = create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    with TestClient(app) as test_client:
        yield test_client


def run_request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "feature": "student-3",
        "task": "Cheapest way for four people from Geelong to Tasmania?",
        "trip_id": "trip_2026_hobart_weekend_escape",
        "context": {"first_search": {"limit": 5}},
        "worker_system": "Suggest transport options with their exact prices.",
        "output_schema": OUTPUT_SCHEMA,
        "grounding": {"source": "student-3", "id_paths": ["items[].id"]},
        "actions_path": "actions",
        "correlation_id": "student3-agents-test",
        "metadata": {"service": "student-3-backend"},
    }
    request.update(overrides)
    return request


SETTLED = {"awaiting_human", "completed", "rejected", "failed"}


def start(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/runs", json=run_request(**overrides))
    assert response.status_code == 202, response.text
    return response.json()["data"]


def settle(client: TestClient, run_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run = client.get(f"/runs/{run_id}").json()["data"]
        if run["status"] in SETTLED:
            return run
        assert time.monotonic() < deadline, f"run stuck in {run['status']}"
        time.sleep(0.02)


def start_and_settle(client: TestClient, **overrides: Any) -> dict[str, Any]:
    return settle(client, start(client, **overrides)["run_id"])
