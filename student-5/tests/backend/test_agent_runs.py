from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings

from .conftest import BUDGET_ID, database_handler

RUN_ID = "magent_0123456789ab"
OTHER_BUDGET_ID = "44444444-4444-4444-8444-444444444444"
ACTIONS = [
    {"category": "food", "new_allocation": "300.00", "reason": "Food is overspent."},
    {"category": "transport", "new_allocation": "200.00", "reason": "Flights."},
]
SUMMARY_TRACE = {
    "tool": "budgets_get_summary",
    "arguments": {"budget_id": BUDGET_ID},
    "status": "success",
    "duration_ms": 31,
    "result": {
        "structuredContent": {
            "ok": True,
            "source": "student-5",
            "data": {"budget_id": BUDGET_ID, "remaining_budget": "899.90"},
        },
        "isError": False,
    },
}
AWAITING = {
    "run_id": RUN_ID,
    "feature": "student-5",
    "task": "Where should I move money?",
    "trip_id": "trip_chunk3",
    "correlation_id": "student5-agents-0123456789ab",
    "status": "awaiting_human",
    "created_at": "2026-10-22T01:00:00Z",
    "updated_at": "2026-10-22T01:02:00Z",
    "attempts": 1,
    "plan": {
        "goal": "Review the food spending.",
        "steps": ["Read the summary", "Read the expenses"],
        "required_evidence": [],
        "tools_to_use": ["budgets_get_summary"],
        "success_criteria": [],
    },
    "steps": [
        {"agent": "planner", "attempt": 1, "status": "completed", "duration_ms": 900},
        {
            "agent": "worker",
            "attempt": 1,
            "status": "completed",
            "duration_ms": 4000,
            "tools": [SUMMARY_TRACE],
        },
        {"agent": "reviewer", "attempt": 1, "status": "completed", "duration_ms": 700},
    ],
    "checks": [
        {"name": "grounding", "passed": True, "blocking": True, "detail": "ok"},
    ],
    "review": {"verdict": "approve", "summary": "Grounded.", "risks": ["Fees"]},
    "result": {
        "budget_id": BUDGET_ID,
        "overview": "AUD 899.90 remains.",
        "findings": ["Food spending is AUD 100.10."],
        "actions": ACTIONS,
    },
    "proposed_actions": ACTIONS,
    "human": None,
    "final_result": None,
    "approved_actions": [],
    "error": None,
}
HISTORY = [
    {
        "sequence": 1,
        "run_id": RUN_ID,
        "at": "2026-10-22T01:00:00Z",
        "actor": "api",
        "event": "run_created",
        "detail": {},
    },
    {
        "sequence": 2,
        "run_id": RUN_ID,
        "at": "2026-10-22T01:03:00Z",
        "actor": "human:Caleb",
        "event": "human_decision",
        "detail": {},
    },
]


class FakeServer:
    def __init__(self, run: dict[str, Any] | None = None) -> None:
        self.run = copy.deepcopy(run or AWAITING)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/runs" and request.method == "POST":
            started = {
                **self.run,
                "status": "planning",
                "steps": [],
                "plan": None,
                "checks": [],
                "review": None,
                "result": None,
                "proposed_actions": [],
            }
            return httpx.Response(202, json={"data": started})
        if path == f"/runs/{RUN_ID}/history":
            return httpx.Response(200, json={"data": HISTORY})
        if path == f"/runs/{RUN_ID}/review":
            body = json.loads(request.content)
            decision = body["decision"]
            approved = {
                "approve": self.run["proposed_actions"],
                "partial": [
                    self.run["proposed_actions"][index]
                    for index in body.get("accepted_actions", [])
                ],
                "correct": (body.get("corrected_result") or {}).get("actions", []),
                "reject": [],
            }[decision]
            self.run |= {
                "status": "rejected" if decision == "reject" else "completed",
                "human": {
                    "decision": decision,
                    "reviewer": body["reviewer"],
                    "notes": body.get("notes"),
                    "decided_at": "2026-10-22T01:03:00Z",
                    "accepted_actions": [],
                },
                "final_result": None
                if decision == "reject"
                else body.get("corrected_result", self.run["result"]),
                "approved_actions": approved,
            }
            return httpx.Response(200, json={"data": self.run})
        if path == f"/runs/{RUN_ID}":
            return httpx.Response(200, json={"data": self.run})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.requests
            if request.url.path == path and request.method == "POST"
        ]


def agent_app(
    settings: Settings,
    server,
    *,
    enabled: bool = True,
    database=database_handler,
) -> TestClient:
    return TestClient(
        create_app(
            replace(settings, multi_agent_enabled=enabled),
            database_transport=httpx.MockTransport(database),
            multi_agent_transport=httpx.MockTransport(server),
        )
    )


def recording_database():
    patches: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            patches.append(json.loads(request.content))
        return database_handler(request)

    return handler, patches


def review(client: TestClient, **body: Any) -> httpx.Response:
    return client.post(
        f"/api/budgets/{BUDGET_ID}/agent-runs/{RUN_ID}/review",
        json={"reviewer": "Caleb"} | body,
    )


def test_disabled_agents_make_no_outbound_call(settings: Settings) -> None:
    server = FakeServer()
    with agent_app(settings, server, enabled=False) as client:
        started = client.post(
            f"/api/budgets/{BUDGET_ID}/agent-runs", json={"question": "On track?"}
        )
        health = client.get("/health").json()["data"]

    assert started.status_code == 503
    assert started.json()["error"]["code"] == "MULTI_AGENT_DISABLED"
    assert server.requests == []
    assert health["integrations"]["multi_agent"] == "disabled"


def test_start_sends_the_budget_prompt_schema_tools_and_grounding(
    settings: Settings,
) -> None:
    server = FakeServer()
    with agent_app(settings, server) as client:
        response = client.post(
            f"/api/budgets/{BUDGET_ID}/agent-runs",
            json={"question": "Where should I move money?"},
        )

    assert response.status_code == 202, response.text
    view = response.json()["data"]
    assert view["run_id"] == RUN_ID
    assert view["status"] == "planning"
    assert view["active"] is True
    [sent] = server.bodies("/runs")
    assert sent["feature"] == "student-5"
    assert sent["task"] == "Where should I move money?"
    assert sent["trip_id"] == "trip_chunk3"
    assert sent["context"]["budget_id"] == BUDGET_ID
    assert sent["context"]["budget_trip_id"] == "trip_chunk3"
    assert sent["context"]["current_allocations"]["food"] == "0.00"
    assert "allowed_tools" not in sent
    assert sent["grounding"] == {
        "source": "student-5",
        "id_paths": ["budget_id"],
        "id_keys": ["budget_id"],
    }
    assert sent["actions_path"] == "actions"
    assert sent["correlation_id"].startswith("student5-agents-")
    assert "budgets_get_summary" in sent["worker_system"]
    assert sent["output_schema"]["type"] == "object"
    assert len(json.dumps(sent["output_schema"])) < 6000
    assert len(json.dumps(sent["context"])) < 4000


def test_a_non_server_trip_id_is_left_to_the_context(settings: Settings) -> None:
    def other_trip(request: httpx.Request) -> httpx.Response:
        response = database_handler(request)
        if request.url.path == f"/internal/budgets/{BUDGET_ID}":
            data = response.json()["data"] | {"trip_id": "trip-7"}
            return httpx.Response(200, json={"data": data})
        return response

    server = FakeServer()
    with agent_app(settings, server, database=other_trip) as client:
        client.post(f"/api/budgets/{BUDGET_ID}/agent-runs", json={"question": "Q?"})

    [sent] = server.bodies("/runs")
    assert sent["trip_id"] is None
    assert sent["context"]["budget_trip_id"] == "trip-7"


def test_an_awaiting_run_shows_every_stage_check_review_and_action(
    settings: Settings,
) -> None:
    with agent_app(settings, FakeServer()) as client:
        response = client.get(f"/api/budgets/{BUDGET_ID}/agent-runs/{RUN_ID}")

    assert response.status_code == 200, response.text
    view = response.json()["data"]
    assert view["active"] is False
    assert view["plan"]["steps"] == ["Read the summary", "Read the expenses"]
    assert [stage["agent"] for stage in view["stages"]] == [
        "planner",
        "worker",
        "reviewer",
    ]
    assert view["stages"][1]["tools"][0]["tool"] == "budgets_get_summary"
    assert view["checks"][0]["passed"] is True
    assert view["review"]["risks"] == ["Fees"]
    assert view["grounded"] is True
    assert view["overview"] == "AUD 899.90 remains."
    assert view["actions"][0] == {
        "index": 0,
        "category": "food",
        "current_allocation": "0.00",
        "new_allocation": "300.00",
        "reason": "Food is overspent.",
    }
    assert view["history"] == []


def test_approving_applies_every_allocation_and_returns_the_audit_history(
    settings: Settings,
) -> None:
    server = FakeServer()
    database, patches = recording_database()
    with agent_app(settings, server, database=database) as client:
        response = review(client, decision="approve", accepted=[0, 1], notes="Fine")

    assert response.status_code == 200, response.text
    view = response.json()["data"]
    assert server.bodies(f"/runs/{RUN_ID}/review") == [
        {"decision": "approve", "reviewer": "Caleb", "notes": "Fine"}
    ]
    assert patches == [{"food_budget": "300.00", "transport_budget": "200.00"}]
    assert view["status"] == "completed"
    assert view["human"]["decision"] == "approve"
    assert view["applied_changes"] == [
        {"category": "food", "previous": "0.00", "new": "300.00"},
        {"category": "transport", "previous": "0.00", "new": "200.00"},
    ]
    assert view["apply_error"] is None
    assert [event["event"] for event in view["history"]] == [
        "run_created",
        "human_decision",
    ]


def test_approving_some_actions_is_a_partial_decision(settings: Settings) -> None:
    server = FakeServer()
    database, patches = recording_database()
    with agent_app(settings, server, database=database) as client:
        response = review(client, decision="approve", accepted=[1])

    assert response.status_code == 200, response.text
    assert server.bodies(f"/runs/{RUN_ID}/review")[0]["decision"] == "partial"
    assert server.bodies(f"/runs/{RUN_ID}/review")[0]["accepted_actions"] == [1]
    assert patches == [{"transport_budget": "200.00"}]


def test_approving_with_no_action_ticked_keeps_the_answer_only(
    settings: Settings,
) -> None:
    server = FakeServer()
    database, patches = recording_database()
    with agent_app(settings, server, database=database) as client:
        response = review(client, decision="approve")

    assert response.status_code == 200, response.text
    [sent] = server.bodies(f"/runs/{RUN_ID}/review")
    assert sent["decision"] == "correct"
    assert sent["corrected_result"]["actions"] == []
    assert patches == []


def test_correcting_replaces_the_overview(settings: Settings) -> None:
    server = FakeServer()
    with agent_app(settings, server) as client:
        response = review(
            client,
            decision="correct",
            accepted=[0, 1],
            corrected_overview="Move AUD 300.00 to food.",
        )

    assert response.status_code == 200, response.text
    [sent] = server.bodies(f"/runs/{RUN_ID}/review")
    assert sent["corrected_result"]["overview"] == "Move AUD 300.00 to food."
    assert response.json()["data"]["overview"] == "Move AUD 300.00 to food."


def test_a_corrected_amount_is_sent_as_a_correction_and_applied(
    settings: Settings,
) -> None:
    server = FakeServer()
    database, patches = recording_database()
    with agent_app(settings, server, database=database) as client:
        response = review(
            client,
            decision="approve",
            accepted=[0, 1],
            corrected_allocations={"0": "450.00", "1": "200.00"},
        )

    assert response.status_code == 200, response.text
    [sent] = server.bodies(f"/runs/{RUN_ID}/review")
    assert sent["decision"] == "correct"
    assert [
        action["new_allocation"] for action in sent["corrected_result"]["actions"]
    ] == [
        "450.00",
        "200.00",
    ]
    assert patches == [{"food_budget": "450.00", "transport_budget": "200.00"}]


def test_a_malformed_corrected_amount_is_rejected(settings: Settings) -> None:
    server = FakeServer()
    with agent_app(settings, server) as client:
        response = review(
            client, decision="approve", accepted=[0], corrected_allocations={"0": "4.5"}
        )

    assert response.status_code == 422
    assert server.bodies(f"/runs/{RUN_ID}/review") == []


def test_a_correction_without_changes_is_rejected_locally(settings: Settings) -> None:
    server = FakeServer()
    with agent_app(settings, server) as client:
        response = review(client, decision="correct", accepted=[0, 1])

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "corrected_overview"
    assert server.bodies(f"/runs/{RUN_ID}/review") == []


def test_rejecting_changes_nothing(settings: Settings) -> None:
    server = FakeServer()
    database, patches = recording_database()
    with agent_app(settings, server, database=database) as client:
        response = review(client, decision="reject", accepted=[0, 1])

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "rejected"
    assert server.bodies(f"/runs/{RUN_ID}/review") == [
        {"decision": "reject", "reviewer": "Caleb"}
    ]
    assert patches == []


def test_allocations_over_the_total_are_not_applied(settings: Settings) -> None:
    run = copy.deepcopy(AWAITING)
    run["proposed_actions"] = run["result"]["actions"] = [
        ACTIONS[0] | {"new_allocation": "900.00"},
        ACTIONS[1],
    ]
    database, patches = recording_database()
    with agent_app(settings, FakeServer(run), database=database) as client:
        response = review(client, decision="approve", accepted=[0, 1])

    view = response.json()["data"]
    assert response.status_code == 200
    assert patches == []
    assert view["applied_changes"] == []
    assert "exceed the total budget" in view["apply_error"]


def test_an_ungrounded_answer_is_never_applied(settings: Settings) -> None:
    run = copy.deepcopy(AWAITING)
    run["steps"][1]["tools"][0]["result"]["structuredContent"]["data"]["budget_id"] = (
        OTHER_BUDGET_ID
    )
    database, patches = recording_database()
    with agent_app(settings, FakeServer(run), database=database) as client:
        detail = client.get(f"/api/budgets/{BUDGET_ID}/agent-runs/{RUN_ID}")
        response = review(client, decision="approve", accepted=[0, 1])

    assert detail.json()["data"]["grounded"] is False
    assert patches == []
    assert "not grounded" in response.json()["data"]["apply_error"]


def test_a_run_from_another_feature_is_not_found(settings: Settings) -> None:
    server = FakeServer(AWAITING | {"feature": "student-3"})
    with agent_app(settings, server) as client:
        response = client.get(f"/api/budgets/{BUDGET_ID}/agent-runs/{RUN_ID}")
        decided = review(client, decision="approve")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"
    assert decided.status_code == 404
    assert server.bodies(f"/runs/{RUN_ID}/review") == []


def test_a_malformed_run_id_is_rejected(settings: Settings) -> None:
    server = FakeServer()
    with agent_app(settings, server) as client:
        response = client.get(f"/api/budgets/{BUDGET_ID}/agent-runs/not-a-run")

    assert response.status_code == 422
    assert server.requests == []


@pytest.mark.parametrize(
    ("status_code", "code", "expected_status", "expected_code"),
    [
        (409, "RUN_NOT_AWAITING_REVIEW", 409, "RUN_NOT_AWAITING_REVIEW"),
        (503, "RUN_LIMIT_REACHED", 503, "RUN_LIMIT_REACHED"),
        (500, "INTERNAL_ERROR", 502, "INVALID_DEPENDENCY_RESPONSE"),
    ],
)
def test_server_errors_are_preserved_or_translated(
    settings: Settings,
    status_code: int,
    code: str,
    expected_status: int,
    expected_code: str,
) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"code": code, "message": "upstream", "details": []}},
        )

    with agent_app(settings, failing) as client:
        response = client.post(
            f"/api/budgets/{BUDGET_ID}/agent-runs", json={"question": "Q?"}
        )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_an_unreachable_server_is_a_dependency_error(settings: Settings) -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with agent_app(settings, offline) as client:
        response = client.get(f"/api/budgets/{BUDGET_ID}/agent-runs/{RUN_ID}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
