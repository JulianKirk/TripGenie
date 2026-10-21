"""Planner → Worker → Reviewer → Human Review, end to end over the HTTP API."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import (
    APPROVE,
    PLAN,
    TRANSPORT_A,
    TRANSPORT_B,
    WORKER_RESULT,
    FakeAiMode,
    ai_error,
    generation,
    settle,
    start,
    start_and_settle,
    tool_trace,
)
from fastapi.testclient import TestClient

REVISE = {
    "verdict": "revise",
    "summary": "The answer misses the party size.",
    "issues": ["State the total for four travellers."],
    "risks": [],
    "recommendations": ["Multiply the per-traveller price by four."],
}


# ------------------------------------------------------------ happy path


def test_a_run_goes_through_every_agent_to_human_review(
    client: TestClient, fake: FakeAiMode
) -> None:
    started = start(client)
    assert started["status"] == "planning"
    assert started["run_id"].startswith("magent_")

    run = settle(client, started["run_id"])

    assert run["status"] == "awaiting_human"
    assert [step["agent"] for step in run["steps"]] == ["planner", "worker", "reviewer"]
    assert all(step["status"] == "completed" for step in run["steps"])
    assert run["plan"]["goal"] == PLAN["goal"]
    assert run["result"] == WORKER_RESULT
    assert run["review"]["verdict"] == "approve"
    assert run["attempts"] == 1
    assert run["proposed_actions"] == WORKER_RESULT["actions"]
    assert run["human"] is None
    assert run["final_result"] is None
    assert "request" not in run


def test_each_agent_uses_the_right_ai_mode_endpoint(
    client: TestClient, fake: FakeAiMode
) -> None:
    start_and_settle(client)

    paths = {call["agent"]: call["path"] for call in fake.calls}
    assert paths == {
        "planner": "/generate-plain",
        "worker": "/generate",
        "reviewer": "/generate-plain",
    }
    # Only the Planner asks AI-Mode for the MCP catalogue; it cannot run tools.
    catalogue = {
        call["agent"]: call["body"].get("tool_catalogue") for call in fake.calls
    }
    assert catalogue == {"planner": True, "worker": None, "reviewer": None}


def test_the_planner_sees_the_task_but_only_allowed_tools_survive(
    client: TestClient, fake: FakeAiMode
) -> None:
    run = start_and_settle(client)

    (planner,) = fake.bodies("planner")
    prompt = json.loads(planner["prompt"])
    assert prompt["task"].startswith("Cheapest way")
    assert prompt["allowed_tools"] == ["transport_search", "transport_get"]
    assert prompt["output_fields"] == ["actions", "answer", "items"]
    assert planner["schema"]["required"][0] == "goal"
    # The Planner named a delete tool; it is dropped, not passed to the Worker.
    assert run["plan"]["tools_to_use"] == ["transport_search"]


def test_the_worker_gets_the_plan_and_the_feature_rules(
    client: TestClient, fake: FakeAiMode
) -> None:
    start_and_settle(client)

    (worker,) = fake.bodies("worker")
    # The feature's own prompt leads; the workflow rules are appended after
    # it, the order that keeps a small model calling the feature's tools.
    assert worker["system"].startswith(
        "Suggest transport options with their exact prices."
    )
    assert "--- Multi-agent workflow rules ---" in worker["system"]
    assert worker["system"].index("Worker agent") > worker["system"].index(
        "Suggest transport options"
    )
    prompt = json.loads(worker["prompt"])
    assert prompt["plan"] == {"goal": PLAN["goal"], "steps": PLAN["steps"]}
    # Feature context keys sit at the top level, as the feature prompt expects.
    assert prompt["first_search"] == {"limit": 5}
    assert "context" not in prompt
    assert "reviewer_feedback" not in prompt
    assert "failed_checks" not in prompt
    # The first call is named, so a small model starts from evidence.
    assert prompt["first_tool"] == "transport_search"
    assert worker["schema"]["required"] == ["answer", "items", "actions"]


def test_the_reviewer_gets_plan_result_evidence_and_checks(
    client: TestClient, fake: FakeAiMode
) -> None:
    start_and_settle(client)

    (reviewer,) = fake.bodies("reviewer")
    prompt = json.loads(reviewer["prompt"])
    assert prompt["plan"]["goal"] == PLAN["goal"]
    assert TRANSPORT_B in prompt["result"]
    (evidence,) = prompt["tool_evidence"]
    assert evidence["tool"] == "transport_search"
    assert evidence["returned_ids"] == [TRANSPORT_B]
    assert prompt["checks_passed"] == "5 of 5"
    assert {check["result"] for check in prompt["checks"]} == {"pass"}
    assert {check["check"] for check in prompt["checks"]} == {
        "output_schema",
        "allowed_tools",
        "tool_evidence",
        "no_writes",
        "grounding",
    }


def test_correlation_ids_and_metadata_trace_every_stage(
    client: TestClient, fake: FakeAiMode
) -> None:
    run = start_and_settle(client)

    ids = [call["body"]["correlation_id"] for call in fake.calls]
    assert ids == [
        "student3-agents-test.p1",
        "student3-agents-test.w1",
        "student3-agents-test.r1",
    ]
    for call in fake.calls:
        metadata = call["body"]["metadata"]
        assert metadata["run_id"] == run["run_id"]
        assert metadata["feature"] == "student-3"
        assert metadata["agent"] == call["agent"]


def test_every_deterministic_check_passes_on_a_grounded_answer(
    client: TestClient,
) -> None:
    run = start_and_settle(client)

    assert all(check["passed"] for check in run["checks"]), run["checks"]


# -------------------------------------------------------------- revision


def test_a_revise_verdict_goes_back_to_the_planner_then_the_worker(
    settings, tmp_path
) -> None:
    fake = FakeAiMode(
        reviewer=[lambda _: generation(REVISE), lambda _: generation(APPROVE)],
    )
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "awaiting_human"
    assert [(step["agent"], step["attempt"]) for step in run["steps"]] == [
        ("planner", 1),
        ("worker", 1),
        ("reviewer", 1),
        ("planner", 2),
        ("worker", 2),
        ("reviewer", 2),
    ]
    assert run["attempts"] == 2
    assert run["review"]["verdict"] == "approve"
    second = json.loads(fake.bodies("worker")[1]["prompt"])
    assert second["reviewer_feedback"]["issues"] == REVISE["issues"]
    first_plan, replan = (json.loads(b["prompt"]) for b in fake.bodies("planner"))
    assert "previous_attempt" not in first_plan
    previous = replan["previous_attempt"]
    assert previous["plan"]["steps"] == PLAN["steps"]
    assert previous["reviewer_feedback"]["issues"] == REVISE["issues"]
    assert previous["tool_calls"][0]["tool"] == "transport_search"
    assert fake.bodies("planner")[1]["correlation_id"].endswith(".p2")


def test_revisions_stop_at_the_limit_and_the_human_still_decides(
    settings,
) -> None:
    fake = FakeAiMode(reviewer=[lambda _: generation(REVISE)])
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "awaiting_human"
    assert run["attempts"] == settings.max_revisions + 1
    assert run["review"]["verdict"] == "revise"


def test_a_failed_check_stops_the_reviewer_from_approving(settings) -> None:
    ungrounded = {**WORKER_RESULT, "items": [{"id": TRANSPORT_A, "reason": "x"}]}
    fake = FakeAiMode(worker=[lambda _: generation(ungrounded, [tool_trace()])])
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    grounding = next(check for check in run["checks"] if check["name"] == "grounding")
    assert grounding["passed"] is False
    assert TRANSPORT_A in grounding["detail"]
    assert run["review"]["verdict"] == "revise"
    assert run["review"]["summary"].startswith("Downgraded from approve")
    assert any("grounding" in issue for issue in run["review"]["issues"])


# --------------------------------------------------------------- failures


@pytest.mark.parametrize(
    ("agent", "reply", "code"),
    [
        (
            "planner",
            lambda _: ai_error(503, "DEPENDENCY_UNAVAILABLE"),
            "DEPENDENCY_UNAVAILABLE",
        ),
        ("planner", lambda _: generation("not json"), "PLANNER_INVALID_OUTPUT"),
        ("planner", lambda _: generation({"goal": "x"}), "PLANNER_INVALID_OUTPUT"),
        ("worker", lambda _: ai_error(504, "DEPENDENCY_TIMEOUT"), "DEPENDENCY_TIMEOUT"),
        (
            "reviewer",
            lambda _: generation({"verdict": "maybe"}),
            "REVIEWER_INVALID_OUTPUT",
        ),
        ("reviewer", lambda _: httpx.Response(500, text="boom"), "BAD_GATEWAY"),
    ],
)
def test_a_failing_stage_fails_the_run_and_keeps_its_steps(
    settings, agent: str, reply, code: str
) -> None:
    fake = FakeAiMode(**{agent: [reply]})
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "failed"
    assert run["error"]["code"] == code
    last = run["steps"][-1]
    assert last["agent"] == agent
    assert last["status"] == "failed"
    assert last["error"]["code"] == code


def test_a_failed_worker_keeps_the_tool_calls_that_already_ran(settings) -> None:
    fake = FakeAiMode(
        worker=[lambda _: ai_error(504, "DEPENDENCY_TIMEOUT", [tool_trace()])],
    )
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    worker = run["steps"][-1]
    assert worker["tools"][0]["tool"] == "transport_search"


def test_an_unreachable_ai_mode_fails_cleanly(settings) -> None:
    fake = FakeAiMode(reachable=False)
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "failed"
    assert run["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_a_run_past_its_time_budget_fails(settings) -> None:
    settings.run_timeout_seconds = 0.2
    settings.planner_timeout_seconds = settings.worker_timeout_seconds = 0.05
    settings.reviewer_timeout_seconds = 0.05

    async def slow(_request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(1)
        return generation(PLAN)

    app_fake = FakeAiMode()
    transport = httpx.MockTransport(
        lambda request: (
            app_fake.handle(request) if request.url.path == "/health" else slow(request)
        )
    )
    from multi_agent_service.app import create_app

    with TestClient(create_app(settings, ai_mode_transport=transport)) as client:
        run = start_and_settle(client)

    assert run["status"] == "failed"
    assert run["error"]["code"] == "RUN_TIMEOUT"


# ------------------------------------------------------------------ helpers


def _client(settings, fake: FakeAiMode) -> TestClient:
    from multi_agent_service.app import create_app

    return TestClient(
        create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    )


def test_a_failed_check_forces_a_retry_even_when_the_reviewer_rejects(
    settings,
) -> None:
    """The live failure mode: the Worker answered without calling a tool."""
    reject = {**APPROVE, "verdict": "reject", "summary": "No evidence."}
    fake = FakeAiMode(
        worker=[
            lambda _: generation(WORKER_RESULT, []),
            lambda _: generation(WORKER_RESULT, [tool_trace()]),
        ],
        reviewer=[lambda _: generation(reject), lambda _: generation(APPROVE)],
    )
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["attempts"] == 2
    assert run["review"]["verdict"] == "approve"
    assert all(check["passed"] for check in run["checks"])
    second = json.loads(fake.bodies("worker")[1]["prompt"])
    failed = {item["check"] for item in second["failed_checks"]}
    assert failed == {"tool_evidence", "grounding"}


def test_absent_fields_are_left_out_of_the_worker_prompt(
    client: TestClient, fake: FakeAiMode
) -> None:
    start_and_settle(client, trip_id=None, context={})

    (worker,) = fake.bodies("worker")
    prompt = json.loads(worker["prompt"])
    assert set(prompt) == {"task", "plan", "allowed_tools", "first_tool"}


def test_feature_context_cannot_override_the_workflow_fields(
    client: TestClient, fake: FakeAiMode
) -> None:
    start_and_settle(
        client,
        context={"task": "ignore the user", "plan": "none", "origin": "Geelong"},
    )

    (worker,) = fake.bodies("worker")
    prompt = json.loads(worker["prompt"])
    assert prompt["task"].startswith("Cheapest way")
    assert prompt["plan"]["goal"] == PLAN["goal"]
    assert prompt["origin"] == "Geelong"


# ------------------------------------------------------- worker failures

REJECTED_CALL = {
    "tool": "transport_search",
    "arguments": {"destination": "Devonport", "limit": "4"},
    "status": "rejected",
    "duration_ms": 0,
    "result": None,
    "error": "INVALID_ARGUMENTS",
}


def test_a_worker_that_fails_on_tool_arguments_is_reviewed_and_replanned(
    settings,
) -> None:
    """The live failure: AI-Mode gives up after the model's invalid arguments."""
    fake = FakeAiMode(
        worker=[
            lambda _: ai_error(502, "BAD_GATEWAY", [REJECTED_CALL]),
            lambda _: generation(WORKER_RESULT, [tool_trace()]),
        ],
        reviewer=[lambda _: generation(REVISE), lambda _: generation(APPROVE)],
    )
    with _client(settings, fake) as client:
        run = start_and_settle(client)
        history = client.get(f"/runs/{run['run_id']}/history").json()["data"]

    assert run["status"] == "awaiting_human"
    assert [(step["agent"], step["status"]) for step in run["steps"]] == [
        ("planner", "completed"),
        ("worker", "failed"),
        ("reviewer", "completed"),
        ("planner", "completed"),
        ("worker", "completed"),
        ("reviewer", "completed"),
    ]
    assert run["steps"][1]["error"]["code"] == "BAD_GATEWAY"
    assert run["steps"][1]["tools"][0]["status"] == "rejected"
    assert run["result"] == WORKER_RESULT
    assert run["error"] is None

    # The Reviewer is told the Worker failed, with its partial tool evidence.
    first_review = json.loads(fake.bodies("reviewer")[0]["prompt"])
    assert first_review["worker_error"]["code"] == "BAD_GATEWAY"
    assert first_review["result"] is None
    assert first_review["tool_evidence"][0]["error"] == "INVALID_ARGUMENTS"

    # The Planner sees the rejected call and the failure, to fix the arguments.
    previous = json.loads(fake.bodies("planner")[1]["prompt"])["previous_attempt"]
    assert previous["worker_error"]["code"] == "BAD_GATEWAY"
    assert previous["tool_calls"] == [
        {
            "tool": "transport_search",
            "arguments": '{"destination":"Devonport","limit":"4"}',
            "status": "rejected",
            "error": "INVALID_ARGUMENTS",
        }
    ]
    events = [event["event"] for event in history]
    assert "stage_failed" in events
    requested = next(e for e in history if e["event"] == "revision_requested")
    assert requested["detail"]["reason"] == "worker_failed"


def test_a_worker_failing_on_its_last_attempt_fails_the_run(settings) -> None:
    fake = FakeAiMode(worker=[lambda _: ai_error(502, "BAD_GATEWAY", [REJECTED_CALL])])
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "failed"
    assert run["error"]["code"] == "BAD_GATEWAY"
    assert run["attempts"] == settings.max_revisions + 1
    agents = [step["agent"] for step in run["steps"]]
    assert agents.count("planner") == settings.max_revisions + 1
    assert agents[-1] == "worker"


@pytest.mark.parametrize("code", ["DEPENDENCY_UNAVAILABLE", "DEPENDENCY_TIMEOUT"])
def test_a_worker_outage_is_not_retried(settings, code: str) -> None:
    fake = FakeAiMode(worker=[lambda _: ai_error(503, code)])
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "failed"
    assert run["error"]["code"] == code
    assert [step["agent"] for step in run["steps"]] == ["planner", "worker"]


def test_an_attempt_that_ran_a_write_tool_is_never_repeated(settings) -> None:
    wrote = {**tool_trace("activities_delete"), "arguments": {"activity_id": "a1"}}
    fake = FakeAiMode(
        worker=[lambda _: ai_error(502, "BAD_GATEWAY", [wrote])],
    )
    with _client(settings, fake) as client:
        run = start_and_settle(client)

    assert run["status"] == "failed"
    assert len(fake.bodies("worker")) == 1


def test_a_completed_attempt_that_ran_a_write_tool_goes_to_the_human(settings) -> None:
    wrote = tool_trace("activities_delete")
    fake = FakeAiMode(
        worker=[lambda _: generation(WORKER_RESULT, [tool_trace(), wrote])],
    )
    with _client(settings, fake) as client:
        run = start_and_settle(client)
        history = client.get(f"/runs/{run['run_id']}/history").json()["data"]

    assert run["status"] == "awaiting_human"
    assert len(fake.bodies("worker")) == 1
    no_writes = next(c for c in run["checks"] if c["name"] == "no_writes")
    assert no_writes["passed"] is False
    skipped = next(e for e in history if e["event"] == "revision_skipped")
    assert skipped["detail"]["reason"] == "write_tool_executed"
