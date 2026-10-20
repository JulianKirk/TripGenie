"""The human's decision is the final step: approve, correct, partial or reject."""

from __future__ import annotations

from conftest import TRANSPORT_B, WORKER_RESULT, start, start_and_settle
from fastapi.testclient import TestClient


def _review(client: TestClient, run_id: str, **body) -> object:
    return client.post(
        f"/runs/{run_id}/review",
        json={"reviewer": "ronit", **body},
    )


def test_approve_completes_the_run_with_every_proposed_action(
    client: TestClient,
) -> None:
    run = start_and_settle(client)

    response = _review(client, run["run_id"], decision="approve", notes="Looks right.")

    assert response.status_code == 200
    final = response.json()["data"]
    assert final["status"] == "completed"
    assert final["human"]["decision"] == "approve"
    assert final["human"]["reviewer"] == "ronit"
    assert final["human"]["notes"] == "Looks right."
    assert final["human"]["accepted_actions"] == [0, 1]
    assert final["final_result"] == WORKER_RESULT
    assert final["approved_actions"] == WORKER_RESULT["actions"]


def test_partial_acceptance_keeps_only_the_chosen_actions(client: TestClient) -> None:
    run = start_and_settle(client)

    final = _review(
        client, run["run_id"], decision="partial", accepted_actions=[0, 0]
    ).json()["data"]

    assert final["status"] == "completed"
    assert final["human"]["accepted_actions"] == [0]
    assert final["approved_actions"] == [WORKER_RESULT["actions"][0]]


def test_a_correction_replaces_the_result_after_schema_validation(
    client: TestClient,
) -> None:
    run = start_and_settle(client)
    corrected = {
        "answer": "Take the ferry; book a cabin for four.",
        "items": [{"id": TRANSPORT_B, "reason": "Overnight crossing."}],
        "actions": [{"type": "add_to_trip", "transport_id": TRANSPORT_B}],
    }

    final = _review(
        client, run["run_id"], decision="correct", corrected_result=corrected
    ).json()["data"]

    assert final["status"] == "completed"
    assert final["final_result"] == corrected
    assert final["approved_actions"] == corrected["actions"]
    assert final["result"] == WORKER_RESULT  # what the agents produced is kept


def test_reject_ends_the_run_with_nothing_approved(client: TestClient) -> None:
    run = start_and_settle(client)

    final = _review(
        client, run["run_id"], decision="reject", notes="Wrong route."
    ).json()["data"]

    assert final["status"] == "rejected"
    assert final["final_result"] is None
    assert final["approved_actions"] == []
    assert final["result"] == WORKER_RESULT


def test_invalid_decisions_are_refused_and_change_nothing(client: TestClient) -> None:
    run = start_and_settle(client)
    run_id = run["run_id"]

    cases = [
        {"decision": "correct"},
        {"decision": "correct", "corrected_result": {"answer": ""}},
        {"decision": "partial"},
        {"decision": "partial", "accepted_actions": [7]},
        {"decision": "approve", "reviewer": ""},
        {"decision": "maybe"},
        {"decision": "approve", "extra": True},
    ]
    for body in cases:
        response = client.post(
            f"/runs/{run_id}/review", json={"reviewer": "ronit", **body}
        )
        assert response.status_code == 422, (body, response.text)
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    assert client.get(f"/runs/{run_id}").json()["data"]["status"] == "awaiting_human"


def test_a_run_can_only_be_decided_once(client: TestClient) -> None:
    run = start_and_settle(client)
    assert _review(client, run["run_id"], decision="approve").status_code == 200

    response = _review(client, run["run_id"], decision="reject")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_AWAITING_REVIEW"


def test_a_failed_run_cannot_be_reviewed(settings) -> None:
    import httpx
    from conftest import FakeAiMode, ai_error
    from multi_agent_service.app import create_app

    fake = FakeAiMode(planner=[lambda _: ai_error(503, "DEPENDENCY_UNAVAILABLE")])
    app = create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    with TestClient(app) as client:
        run = start_and_settle(client)
        response = _review(client, run["run_id"], decision="approve")

    assert response.status_code == 409


def test_unknown_and_malformed_run_ids(client: TestClient) -> None:
    missing = client.post(
        "/runs/magent_000000000000/review",
        json={"decision": "approve", "reviewer": "ronit"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"

    malformed = client.get("/runs/not-a-run")
    assert malformed.status_code == 422


def test_the_decision_is_in_the_audit_history(client: TestClient) -> None:
    run = start_and_settle(client)
    _review(client, run["run_id"], decision="approve")

    events = client.get(f"/runs/{run['run_id']}/history").json()["data"]

    decision = next(event for event in events if event["event"] == "human_decision")
    assert decision["actor"] == "human:ronit"
    assert decision["detail"]["decision"] == "approve"
    assert events[-1]["event"] == "run_completed"


def test_reviewing_before_the_agents_finish_is_refused(settings) -> None:
    import asyncio
    import threading

    import httpx
    from conftest import PLAN, FakeAiMode, generation, settle
    from multi_agent_service.app import create_app

    release = threading.Event()
    fake = FakeAiMode()

    async def held_planner(request: httpx.Request) -> httpx.Response:
        await asyncio.to_thread(release.wait, 5)
        return generation(PLAN)

    def route(request: httpx.Request):
        body = request.content and request.read()
        if request.url.path == "/generate-plain" and b'"agent":"planner"' in (
            body or b""
        ).replace(b" ", b""):
            return held_planner(request)
        return fake.handle(request)

    app = create_app(settings, ai_mode_transport=httpx.MockTransport(route))
    with TestClient(app) as client:
        run = start(client)
        response = _review(client, run["run_id"], decision="approve")
        release.set()
        settled = settle(client, run["run_id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_AWAITING_REVIEW"
    assert "planning" in response.json()["error"]["message"]
    assert settled["status"] == "awaiting_human"
