from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

RUN = "magent_0123456789ab"
PATH = f"/activity/planner/runs/{RUN}"


def record(**changes: Any) -> dict[str, Any]:
    return {
        "run_id": RUN,
        "feature": "student-4",
        "task": "Find outdoor activities",
        "status": "awaiting_human",
        "steps": [],
        "checks": [],
        "result": {"type": "final", "parts": [{"type": "text", "text": "No matches."}]},
        **changes,
    }


def test_disabled_planner_does_not_contact_dependencies() -> None:
    with TestClient(create_app(Settings(multi_agent_enabled=False))) as client:
        response = client.post(
            "/activity/planner/runs", json={"question": "Find activities"}
        )
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_start_sends_feature_owned_contract() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202, json={"data": record(status="planning", result=None)}
        )

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        response = client.post(
            "/activity/planner/runs",
            json={"question": "Find activities", "trip_id": "trip_sydney"},
        )
    assert response.status_code == 202
    body = json.loads(requests[0].content)
    assert body["feature"] == "student-4"
    assert body["trip_id"] == "trip_sydney"
    assert body["grounding"]["id_paths"] == ["parts[].activity_id"]
    assert "activities_search" in body["allowed_tools"]
    assert "output_schema" in body and "worker_system" in body
    assert "actions_path" not in body


@pytest.mark.parametrize("feature", ["student-1", "student-3"])
def test_other_features_cannot_be_reviewed(feature: str) -> None:
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"data": record(feature=feature)})

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        response = client.post(
            f"{PATH}/review", json={"decision": "approve", "reviewer": "Julian"}
        )
    assert response.status_code == 404
    assert methods == ["GET"]


def test_review_forwards_human_decision_and_never_retries() -> None:
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            msg = "private dependency details"
            raise httpx.ReadTimeout(msg)
        return httpx.Response(200, json={"data": record()})

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        response = client.post(
            f"{PATH}/review", json={"decision": "approve", "reviewer": "Julian"}
        )
    assert response.status_code == 504
    assert "private" not in response.text
    assert methods == ["GET", "POST"]


def test_ungrounded_activity_is_not_displayed_or_approved() -> None:
    data = record(
        result={
            "type": "final",
            "parts": [
                {
                    "type": "activity",
                    "activity_id": "00000000-0000-0000-0000-000000000001",
                }
            ],
        }
    )
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"data": data})

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        fetched = client.get(PATH)
        reviewed = client.post(
            f"{PATH}/review", json={"decision": "approve", "reviewer": "Julian"}
        )
    assert fetched.status_code == 200
    assert fetched.json()["answer"]["activities"] == {}
    assert fetched.json()["answer"]["error"]
    assert reviewed.status_code == 400
    assert methods == ["GET", "GET"]


@pytest.mark.parametrize("status", [404, 409, 503])
def test_shared_errors_are_preserved_without_raw_details(status: int) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(status, json={"error": {"message": "private"}})
    )
    with TestClient(
        create_app(Settings(multi_agent_enabled=True), multi_agent_transport=transport)
    ) as client:
        response = client.get(PATH)
    assert response.status_code == status
    assert "private" not in response.text


def test_history_keeps_agent_outputs_and_human_audit() -> None:
    run = record(
        steps=[
            {
                "agent": "planner",
                "attempt": 1,
                "status": "completed",
                "output": {"goal": "Find a walk"},
                "duration_ms": 42,
            }
        ]
    )
    event = {
        "sequence": 1,
        "run_id": RUN,
        "at": "2026-10-21T00:00:00Z",
        "actor": "planner",
        "event": "stage_completed",
        "detail": {},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [event] if request.url.path.endswith("/history") else run},
        )

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        response = client.get(f"{PATH}/history")
    assert response.status_code == 200
    assert response.json()["run"]["steps"][0]["output"] == {"goal": "Find a walk"}
    assert response.json()["history"][0]["actor"] == "planner"


@pytest.mark.parametrize("decision", ["approve", "correct", "reject"])
def test_human_decisions_are_recorded(decision: str) -> None:
    submitted: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            submitted.append(body)
            return httpx.Response(
                200,
                json={
                    "data": record(
                        status="rejected" if decision == "reject" else "completed",
                        human={"decision": decision, "reviewer": "Julian"},
                        final_result=body.get("corrected_result", record()["result"]),
                    )
                },
            )
        return httpx.Response(200, json={"data": record()})

    body: dict[str, Any] = {"decision": decision, "reviewer": "Julian"}
    if decision == "correct":
        body["corrected_result"] = {
            "type": "final",
            "parts": [{"type": "text", "text": "My correction"}],
        }
    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        response = client.post(f"{PATH}/review", json=body)
    assert response.status_code == 200
    assert response.json()["run"]["human"]["decision"] == decision
    assert submitted[0]["decision"] == decision


@pytest.mark.parametrize("data", [{}, {"run_id": "bad"}, {"data": "bad"}])
def test_malformed_runs_return_bad_gateway(data: dict[str, Any]) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"data": data}))
    with TestClient(
        create_app(Settings(multi_agent_enabled=True), multi_agent_transport=transport)
    ) as client:
        assert client.get(PATH).status_code == 502


def test_failed_checks_block_approval_but_allow_rejection() -> None:
    run = record(
        checks=[
            {
                "name": "no_writes",
                "passed": False,
                "blocking": True,
                "detail": "Write detected",
            }
        ]
    )
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"data": run})

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        assert (
            client.post(
                f"{PATH}/review", json={"decision": "approve", "reviewer": "Julian"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"{PATH}/review", json={"decision": "reject", "reviewer": "Julian"}
            ).status_code
            == 200
        )
    assert methods == ["GET", "GET", "POST"]


def test_planner_is_enabled_by_default_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDENT4_BACKEND_MULTI_AGENT_ENABLED", raising=False)
    assert Settings().multi_agent_enabled is True
    assert Settings.from_env().multi_agent_enabled is True


@pytest.mark.parametrize("enabled", ["false", "0"])
def test_planner_can_be_disabled_for_ci_and_cloud(
    monkeypatch: pytest.MonkeyPatch, enabled: str
) -> None:
    monkeypatch.setenv("STUDENT4_BACKEND_MULTI_AGENT_ENABLED", enabled)
    assert Settings.from_env().multi_agent_enabled is False


@pytest.mark.parametrize("with_correction", [False, True])
def test_approval_cannot_substitute_a_correction_for_an_invalid_original(
    with_correction: bool,
) -> None:
    activity_id = "00000000-0000-0000-0000-000000000001"
    data = record(
        result={
            "type": "final",
            "parts": [{"type": "activity", "activity_id": activity_id}] * 7,
        },
        steps=[
            {
                "agent": "worker",
                "attempt": 1,
                "status": "completed",
                "tools": [
                    {
                        "tool": "activities_search",
                        "arguments": {},
                        "status": "success",
                        "duration_ms": 1,
                        "result": {
                            "structuredContent": {
                                "source": "student-4",
                                "ok": True,
                                "data": {"items": [{"id": activity_id}]},
                            }
                        },
                    }
                ],
            }
        ],
    )
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"data": data})

    body: dict[str, Any] = {"decision": "approve", "reviewer": "Julian"}
    if with_correction:
        body["corrected_result"] = {
            "type": "final",
            "parts": [{"type": "text", "text": "A separate valid correction."}],
        }
    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(handle),
        )
    ) as client:
        response = client.post(f"{PATH}/review", json=body)
    assert response.status_code == 400
    assert methods == ["GET"]
