"""The gateway catalogue, not a caller list, defines feature availability."""

import json

import httpx
import pytest
from conftest import (
    PLAN,
    WORKER_RESULT,
    FakeAiMode,
    generation,
    start_and_settle,
    tool_trace,
)
from fastapi.testclient import TestClient
from multi_agent_service.app import create_app


def scoped(body, names, tools=None):
    data = generation(body, tools).json()
    data["data"]["available_tools"] = names
    return httpx.Response(200, json=data)


def test_feature_selects_gateway_snapshot_without_caller_list(settings):
    fake = FakeAiMode(
        planner=[lambda _: scoped(PLAN, ["transport_search"])],
        worker=[lambda _: scoped(WORKER_RESULT, ["transport_search"], [tool_trace()])],
    )
    with TestClient(
        create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    ) as client:
        run = start_and_settle(client)
    assert run["status"] == "awaiting_human"
    assert all(check["passed"] for check in run["checks"])
    for call in fake.calls:
        assert call["body"]["feature"] == "student-3"
        assert "allowed_tools" not in json.loads(call["body"]["prompt"])
    assert run["plan"]["tools_to_use"] == ["transport_search"]
    assert run["steps"][1]["available_tools"] == ["transport_search"]


@pytest.mark.parametrize("agent", ["planner", "worker"])
@pytest.mark.parametrize("names", [None, [], "transport_search", [42]])
def test_successful_scoped_response_requires_valid_catalogue(settings, agent, names):
    def invalid(_):
        data = generation(PLAN if agent == "planner" else WORKER_RESULT).json()
        if names is None:
            data["data"].pop("available_tools", None)
        else:
            data["data"]["available_tools"] = names
        return httpx.Response(200, json=data)

    fake = FakeAiMode(**{agent: [invalid]})
    with TestClient(
        create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    ) as client:
        run = start_and_settle(client)
    assert any(
        step["error"] and step["error"]["code"] == "BAD_GATEWAY"
        for step in run["steps"]
    )


def test_feature_request_requires_tool_evidence(client, fake):
    fake.worker = [lambda _: scoped(WORKER_RESULT, ["transport_search"])]
    run = start_and_settle(client)
    checks = {check["name"]: check for check in run["checks"]}
    assert checks["tool_evidence"]["passed"] is False


def test_foreign_worker_call_blocks_human_acceptance_but_allows_rejection(settings):
    fake = FakeAiMode(
        worker=[
            lambda _: scoped(
                WORKER_RESULT, ["transport_search"], [tool_trace("activities_search")]
            )
        ]
    )
    with TestClient(
        create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    ) as client:
        run = start_and_settle(client)
        assert any(c["name"] == "tool_scope" and not c["passed"] for c in run["checks"])
        path = f"/runs/{run['run_id']}/review"
        response = client.post(path, json={"decision": "approve", "reviewer": "test"})
        assert response.status_code == 422
        response = client.post(path, json={"decision": "reject", "reviewer": "test"})
        assert response.status_code == 200


def test_pre_snapshot_completed_worker_keeps_existing_review_contract(client):
    run = start_and_settle(client)
    stored = client.app.state.store.get(run["run_id"])
    assert stored is not None
    for step in stored.steps:
        step.available_tools = []
    client.app.state.store.save(stored)
    assert client.get(f"/runs/{run['run_id']}").status_code == 200
    response = client.post(
        f"/runs/{run['run_id']}/review",
        json={"decision": "approve", "reviewer": "legacy-review"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "completed"
