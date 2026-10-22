"""The HTTP contract: validation, history, export, health and limits."""

from __future__ import annotations

import logging

import httpx
import pytest
from conftest import (
    OUTPUT_SCHEMA,
    FakeAiMode,
    run_request,
    start_and_settle,
)
from fastapi.testclient import TestClient
from multi_agent_service.app import create_app

# ------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"feature": "student-9"}, "feature"),
        ({"feature": "Student 3"}, "feature"),
        ({"task": ""}, "task"),
        ({"task": "x" * 501}, "task"),
        ({"output_schema": {"type": "array"}}, "output_schema"),
        ({"output_schema": {"type": "object", "properties": 3}}, "output_schema"),
        (
            {"output_schema": {"type": "object", "$ref": "https://evil/schema"}},
            "output_schema",
        ),
        ({"context": {"blob": "x" * 5000}}, "context"),
        ({"worker_system": "x" * 6001}, "worker_system"),
        ({"feature_instructions": "x" * 6001}, "feature_instructions"),
        (
            {"worker_system": "x" * 3000, "feature_instructions": "y" * 3001},
            "feature_instructions",
        ),
        ({"allowed_tools": ["transport_search", "transport_search"]}, "allowed_tools"),
        ({"allowed_tools": ["Bad Tool"]}, "allowed_tools.0"),
        (
            {"grounding": {"source": "student-3", "id_paths": ["a..b"]}},
            "grounding.id_paths",
        ),
        ({"trip_id": "hobart"}, "trip_id"),
        ({"correlation_id": "has spaces"}, "correlation_id"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_bad_requests_are_refused_before_any_agent_runs(
    client: TestClient,
    fake: FakeAiMode,
    override: dict,
    field: str,
) -> None:
    response = client.post("/runs", json=run_request(**override))

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(detail["field"].startswith(field) for detail in error["details"]), error
    assert fake.calls == []


def test_the_request_is_not_echoed_back(client: TestClient) -> None:
    run = start_and_settle(client)

    assert "request" not in run
    assert "worker_system" not in str(run)


# -------------------------------------------------------- history/export


def test_history_records_every_transition_in_order(client: TestClient) -> None:
    run = start_and_settle(client)

    events = client.get(f"/runs/{run['run_id']}/history").json()["data"]

    names = [event["event"] for event in events]
    assert names == [
        "run_created",
        "stage_started",
        "stage_completed",
        "stage_started",
        "stage_completed",
        "checks_completed",
        "stage_started",
        "review_completed",
        "awaiting_human",
    ]
    assert [event["actor"] for event in events[:3]] == ["api", "planner", "planner"]
    assert [event["sequence"] for event in events] == sorted(
        event["sequence"] for event in events
    )
    worker_done = events[4]["detail"]
    assert worker_done["tool_calls"] == ["transport_search:success"]


def test_export_as_json_summarises_the_workflow(client: TestClient) -> None:
    run = start_and_settle(client)
    client.post(
        f"/runs/{run['run_id']}/review",
        json={"decision": "approve", "reviewer": "ronit"},
    )

    document = client.get(f"/runs/{run['run_id']}/export").json()["data"]

    assert document["schema_version"] == "1"
    summary = document["summary"]
    assert [stage["agent"] for stage in summary["stages"]] == [
        "planner",
        "worker",
        "reviewer",
    ]
    assert summary["verdict"] == "approve"
    assert summary["human_decision"] == "approve"
    assert summary["final_status"] == "completed"
    assert document["history"][-1]["event"] == "run_completed"


def test_export_as_markdown_is_report_ready(client: TestClient) -> None:
    run = start_and_settle(client)

    response = client.get(f"/runs/{run['run_id']}/export?format=markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    text = response.text
    for heading in (
        f"# Multi-agent run {run['run_id']}",
        "## Plan (Planner)",
        "## Stages",
        "## Deterministic checks",
        "## Review (Reviewer)",
        "## Human review",
        "## Coordination and audit log",
    ):
        assert heading in text
    assert "_Awaiting a decision._" in text


def test_runs_can_be_listed_and_filtered(client: TestClient) -> None:
    first = start_and_settle(client)
    start_and_settle(client, feature="student-1", allowed_tools=[], grounding=None)

    everything = client.get("/runs").json()["data"]
    transport = client.get("/runs?feature=student-3").json()["data"]
    waiting = client.get("/runs?status=awaiting_human&limit=1").json()["data"]

    assert len(everything) == 2
    assert [run["run_id"] for run in transport] == [first["run_id"]]
    assert transport[0]["verdict"] == "approve"
    assert len(waiting) == 1
    assert client.get("/runs?limit=0").status_code == 422


# ---------------------------------------------------------- operations


def test_health_and_ready_when_everything_works(client: TestClient) -> None:
    health = client.get("/health").json()["data"]
    ready = client.get("/ready")

    assert health["status"] == "ok"
    assert health["dependencies"]["ai_mode"]["status"] == "ok"
    assert health["dependencies"]["store"]["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"


@pytest.mark.parametrize(
    ("fake", "ai_status"),
    [
        (FakeAiMode(reachable=False), "unavailable"),
        (FakeAiMode(health_status="degraded"), "degraded"),
    ],
)
def test_health_stays_200_but_ready_fails_without_ai_mode(
    settings, fake: FakeAiMode, ai_status: str
) -> None:
    app = create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["data"]["dependencies"]["ai_mode"]["status"] == ai_status
    assert ready.status_code == 503
    assert ready.json()["data"]["status"] == "unavailable"


def test_the_active_run_limit_is_enforced(client: TestClient) -> None:
    engine = client.app.state.engine
    limit = client.app.state.settings.max_active_runs
    for index in range(limit):
        engine._tasks[f"placeholder_{index}"] = object()

    response = client.post("/runs", json=run_request())

    engine._tasks.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RUN_LIMIT_REACHED"


def test_logs_carry_ids_and_statuses_never_the_task(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="multi_agent_service.workflow"):
        run = start_and_settle(client)

    assert f"run_id={run['run_id']}" in caplog.text
    assert "status=awaiting_human" in caplog.text
    assert "Geelong" not in caplog.text
    assert OUTPUT_SCHEMA["required"][0] not in caplog.text
