"""Release 2 "Plan my itinerary": the backend side of the multi-agent workflow.

The shared Multi-Agent Server is faked over an injected httpx transport with
the run semantics its workflow implements (start -> awaiting_human -> one
human decision); no Ollama, AI-Mode or live host service is involved.
"""

from __future__ import annotations

import json
from copy import deepcopy

import httpx
import pytest
from backend_service.config import Settings
from backend_service.multi_agent_plan import (
    CONTEXT_MAX_CHARS,
    RULES_ASSET,
    bounded_context,
)
from backend_service.prompt_assets import load_prompt_asset
from conftest import error_response

TRIP = "trip_2027_sydney_getaway"
OTHER_TRIP = "trip_2027_tokyo_city_break"
NOW = "2027-01-01T00:00:00Z"
ENABLED = Settings(
    database_api_base_url="http://database.test",
    multi_agent_enabled=True,
)
ITEMS = [
    {
        "date": "2027-04-02",
        "start_time": "14:00",
        "end_time": "16:00",
        "title": "Opera House tour",
        "location": "Bennelong Point",
        "description": "Guided tour.",
        "category": "activity",
        "source_id": "act_opera",
    },
    {
        "date": "2027-04-03",
        "start_time": "08:00",
        "end_time": "09:00",
        "title": "Breakfast",
        "location": None,
        "description": None,
        "category": "meal",
        "source_id": None,
    },
]


def draft(**overrides: object) -> dict[str, object]:
    item = deepcopy(ITEMS[0])
    item.update(overrides)
    return item


class FakeMultiAgent:
    """The Multi-Agent Server's run API, as multi_agent_service.workflow
    implements it: the server records decisions and never writes trips."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, object]] = {}
        self.requests: list[tuple[str, str, object]] = []
        self.response: httpx.Response | Exception | None = None
        self.decide_before_review: str | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if isinstance(self.response, Exception):
            raise self.response
        if self.response is not None:
            return self.response
        parts = request.url.path.strip("/").split("/")
        if request.method == "POST" and parts == ["runs"]:
            run_id = f"magent_{len(self.runs) + 1:012x}"
            self.runs[run_id] = {
                "run_id": run_id,
                "feature": body["feature"],
                "task": body["task"],
                "trip_id": body["trip_id"],
                "correlation_id": body["correlation_id"],
                "status": "planning",
                "created_at": NOW,
                "updated_at": NOW,
                "attempts": 0,
                "steps": [],
                "checks": [],
                "proposed_actions": [],
                "approved_actions": [],
                "new_upstream_field": "ignored",
            }
            return httpx.Response(202, json={"data": self.runs[run_id]})
        run = self.runs.get(parts[1])
        if run is None:
            return error_response(404, "RUN_NOT_FOUND", "Run was not found.")
        if request.method == "GET":
            return httpx.Response(200, json={"data": run})
        if self.decide_before_review:
            self._decide(run, {"decision": self.decide_before_review})
            self.decide_before_review = None
        if run["status"] != "awaiting_human":
            return error_response(409, "RUN_NOT_AWAITING_REVIEW", "Not awaiting.")
        return self._decide(run, body)

    def _decide(self, run: dict[str, object], body: dict) -> httpx.Response:
        proposed = run["proposed_actions"]
        decision = body["decision"]
        final, approved, accepted = run["result"], [], []
        if decision == "approve":
            approved, accepted = list(proposed), list(range(len(proposed)))
        elif decision == "correct":
            final = body["corrected_result"]
            approved = final["items"]
            accepted = list(range(len(approved)))
        elif decision == "partial":
            accepted = sorted(set(body["accepted_actions"]))
            approved = [proposed[index] for index in accepted]
        else:
            final = None
        run.update(
            status="rejected" if decision == "reject" else "completed",
            human={
                "decision": decision,
                "reviewer": body.get("reviewer", "traveller"),
                "notes": body.get("notes"),
                "decided_at": NOW,
                "accepted_actions": accepted,
            },
            final_result=final,
            approved_actions=approved,
        )
        return httpx.Response(200, json={"data": run})

    def awaiting(self, run_id: str, items: list[dict[str, object]]) -> None:
        self.runs[run_id].update(
            status="awaiting_human",
            attempts=1,
            plan={
                "goal": "Plan the Sydney days",
                "steps": ["Read the trip", "Draft items"],
                "required_evidence": ["trip_get_context"],
                "tools_to_use": ["trip_get_context"],
                "success_criteria": ["Dates inside the trip"],
            },
            steps=[
                {
                    "agent": "worker",
                    "attempt": 1,
                    "status": "completed",
                    "started_at": NOW,
                    "duration_ms": 1200,
                    "model": "llama3.1:8b",
                    "tools": [
                        {
                            "tool": "trip_get_context",
                            "arguments": {"trip_id": TRIP},
                            "status": "success",
                            "duration_ms": 30,
                            "result": {
                                "structuredContent": {
                                    "ok": True,
                                    "source": "student-1",
                                    "data": {"id": TRIP},
                                },
                            },
                        },
                    ],
                },
            ],
            checks=[
                {
                    "name": "grounding",
                    "passed": False,
                    "blocking": True,
                    "detail": "1 id not returned by a tool",
                },
            ],
            review={
                "verdict": "revise",
                "summary": "Mostly grounded.",
                "issues": [],
                "risks": ["Breakfast has no evidence."],
                "recommendations": ["Check the tour time."],
            },
            result={"summary": "Two days planned.", "items": deepcopy(items)},
            proposed_actions=deepcopy(items),
        )

    def review_calls(self) -> list[object]:
        return [body for method, path, body in self.requests if "review" in path]


@pytest.fixture
def multi_agent() -> FakeMultiAgent:
    return FakeMultiAgent()


@pytest.fixture
def api(client_factory, database_api, multi_agent):
    database_api.trip_activities[(TRIP, "act_opera")] = {
        "trip_id": TRIP,
        "activity_id": "act_opera",
        "date": "2027-04-02",
        "start_time": "14:00",
    }
    with client_factory(
        database_api.handle,
        settings_override=ENABLED,
        multi_agent_handler=multi_agent.handle,
    ) as client:
        yield client


def start(api) -> dict[str, object]:
    response = api.post(f"/api/trips/{TRIP}/multi-agent-plan", json={})
    assert response.status_code == 202, response.text
    return response.json()["data"]


def awaiting(api, multi_agent, items=ITEMS) -> str:
    run_id = start(api)["run_id"]
    multi_agent.awaiting(run_id, items)
    return run_id


def review(api, run_id: str, **body: object) -> httpx.Response:
    return api.post(f"/api/trips/{TRIP}/multi-agent-plan/{run_id}/review", json=body)


def plan_items(database_api, run_id: str) -> dict[str, dict[str, object]]:
    return {
        item_id: item
        for item_id, item in database_api.items.items()
        if item_id.startswith(f"item_{run_id}_")
    }


def test_start_sends_the_student_1_run_contract(api, multi_agent) -> None:
    data = start(api)

    _, path, sent = multi_agent.requests[0]
    assert path == "/runs"
    assert sent["feature"] == "student-1"
    assert sent["trip_id"] == TRIP
    assert sent["allowed_tools"] == ["trip_get_context", "trips_list_itinerary_items"]
    assert sent["actions_path"] == "items"
    assert sent["grounding"]["id_paths"] == ["items[].source_id"]
    assert sent["output_schema"]["type"] == "object"
    assert sent["correlation_id"].startswith("student1-plan-")
    assert "trip_get_context" in sent["worker_system"]
    # Planner/Reviewer rules ride in feature_instructions, sharing the server's
    # 6,000-character system allowance with the Worker prompt.
    assert sent["feature_instructions"] == load_prompt_asset(RULES_ASSET)
    assert sent["feature_instructions"] != sent["worker_system"]
    assert len(sent["feature_instructions"]) + len(sent["worker_system"]) <= 6000
    assert len(sent["task"]) <= 500
    context = sent["context"]
    assert context["trip"]["start_date"] == "2027-04-01"
    assert context["activities"] == [
        {"activity_id": "act_opera", "date": "2027-04-02", "start_time": "14:00"}
    ]
    assert {item["title"] for item in context["existing_items"]} == {
        "Harbour Walk",
        "Waterside Dinner",
    }
    assert data["status"] == "planning"
    assert data["active"] is True
    assert data["items"] == []


def test_context_is_trimmed_under_the_server_limit() -> None:
    detail = {
        "id": TRIP,
        "name": "n" * 255,
        "destination": "d" * 255,
        "start_date": "2027-04-01",
        "end_date": "2027-04-30",
        "traveller_count": 2,
        "notes": "x" * 2000,
        "days": [
            {
                "date": "2027-04-01",
                "items": [
                    {
                        "id": f"item_{n:03d}",
                        "date": "2027-04-01",
                        "title": "t" * 255,
                        "category": "note",
                    }
                    for n in range(40)
                ],
            },
        ],
        "activities": [
            {"activity_id": f"act_{n}", "name": "a" * 200, "date": "2027-04-02"}
            for n in range(40)
        ],
    }

    context = bounded_context(detail)

    assert len(json.dumps(context)) <= CONTEXT_MAX_CHARS
    assert context["truncated"] is True
    assert context["existing_items"][0]["id"] == "item_000"
    assert len(context["trip"]["notes"]) == 300


def test_poll_shows_the_plan_evidence_checks_and_item_problems(
    api, multi_agent
) -> None:
    run_id = awaiting(
        api,
        multi_agent,
        [
            ITEMS[0],
            draft(date="2027-05-09", title="Out of trip", source_id=None),
            draft(
                date="2027-04-02",
                start_time="09:30",
                end_time="10:00",
                title="Coffee",
                source_id="act_unknown",
            ),
            {"date": "tomorrow", "title": "", "category": "party"},
        ],
    )

    response = api.get(f"/api/trips/{TRIP}/multi-agent-plan/{run_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "awaiting_human"
    assert data["active"] is False
    assert data["plan"]["goal"] == "Plan the Sydney days"
    assert data["steps"][0]["tools"][0]["tool"] == "trip_get_context"
    assert data["steps"][0]["tools"][0]["data"] == {"id": TRIP}
    assert data["checks"][0]["passed"] is False
    assert data["review"]["risks"] == ["Breakfast has no evidence."]
    assert data["summary"] == "Two days planned."
    supported, outside, clash, malformed = data["items"]
    assert supported["problems"] == [] and supported["warnings"] == []
    assert outside["problems"] == ["date must fall between 2027-04-01 and 2027-04-03"]
    assert clash["problems"] == []
    assert clash["warnings"] == [
        "Source 'act_unknown' is not saved on this trip.",
        "Overlaps 'Harbour Walk' at 09:00.",
    ]
    assert malformed["title"] == ""
    assert len(malformed["problems"]) == 3


def test_a_revised_run_shows_the_failed_attempt_and_saves_the_final_draft(
    api, multi_agent, database_api
) -> None:
    # The server re-plans after a Worker failure; the failed step stays in the
    # audit trail with an error and no result, and only the result is saved.
    run_id = awaiting(api, multi_agent)
    run = multi_agent.runs[run_id]
    worker = run["steps"][0]
    failed = {
        **deepcopy(worker),
        "status": "failed",
        "error": {"code": "BAD_GATEWAY", "message": "AI-Mode returned bad JSON."},
    }
    replan = {"agent": "planner", "attempt": 2, "status": "completed", "tools": []}
    run.update(attempts=2, steps=[failed, replan, {**worker, "attempt": 2}])

    data = api.get(f"/api/trips/{TRIP}/multi-agent-plan/{run_id}").json()["data"]

    assert data["attempts"] == 2
    assert [(s["agent"], s["attempt"], s["status"]) for s in data["steps"]] == [
        ("worker", 1, "failed"),
        ("planner", 2, "completed"),
        ("worker", 2, "completed"),
    ]
    assert data["steps"][0]["error"] == "AI-Mode returned bad JSON."
    assert review(api, run_id, decision="approve").status_code == 200
    assert set(plan_items(database_api, run_id)) == {
        f"item_{run_id}_0",
        f"item_{run_id}_1",
    }


def test_disabled_planner_is_an_explicit_503_and_never_calls_the_server(
    client_factory, database_api, multi_agent
) -> None:
    with client_factory(
        database_api.handle, multi_agent_handler=multi_agent.handle
    ) as client:
        responses = [
            client.post(f"/api/trips/{TRIP}/multi-agent-plan"),
            client.get(f"/api/trips/{TRIP}/multi-agent-plan/magent_000000000001"),
            client.post(
                f"/api/trips/{TRIP}/multi-agent-plan/magent_000000000001/review",
                json={"decision": "reject"},
            ),
        ]

    for response in responses:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MULTI_AGENT_DISABLED"
    assert multi_agent.requests == []


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (httpx.ConnectError("refused"), 503, "DEPENDENCY_UNAVAILABLE"),
        (httpx.ReadTimeout("slow"), 504, "DEPENDENCY_TIMEOUT"),
        (error_response(503, "RUN_LIMIT_REACHED", "Full."), 503, "RUN_LIMIT_REACHED"),
        (httpx.Response(500, text="boom"), 502, "BAD_GATEWAY"),
        (httpx.Response(202, json={"data": {"run_id": "nope"}}), 502, "BAD_GATEWAY"),
        (httpx.Response(202, text="not json"), 502, "BAD_GATEWAY"),
        (error_response(422, "VALIDATION_ERROR", "Bad."), 502, "BAD_GATEWAY"),
    ],
)
def test_server_failures_map_to_clear_errors(
    api, multi_agent, failure, status, code
) -> None:
    multi_agent.response = failure

    response = api.post(f"/api/trips/{TRIP}/multi-agent-plan", json={})

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_a_run_for_another_trip_or_request_is_rejected_at_start(
    api, multi_agent
) -> None:
    multi_agent.response = httpx.Response(
        202,
        json={
            "data": {
                "run_id": "magent_000000000009",
                "feature": "student-1",
                "task": "x",
                "trip_id": OTHER_TRIP,
                "correlation_id": "student1-plan-000000000000",
                "status": "planning",
                "created_at": NOW,
                "updated_at": NOW,
            },
        },
    )

    response = api.post(f"/api/trips/{TRIP}/multi-agent-plan", json={})

    assert response.status_code == 502


def test_runs_are_only_visible_from_the_trip_and_feature_that_started_them(
    api, multi_agent
) -> None:
    run_id = awaiting(api, multi_agent)
    multi_agent.runs["magent_0000000000ff"] = {
        **multi_agent.runs[run_id],
        "run_id": "magent_0000000000ff",
        "feature": "student-3",
    }

    other_trip_url = f"/api/trips/{OTHER_TRIP}/multi-agent-plan/{run_id}"
    assert api.get(other_trip_url).status_code == 404
    assert (
        api.get(f"/api/trips/{TRIP}/multi-agent-plan/magent_0000000000ff").status_code
        == 404
    )
    assert (
        api.get(f"/api/trips/{TRIP}/multi-agent-plan/magent_00000000beef").status_code
        == 404
    )
    assert api.get(f"/api/trips/{TRIP}/multi-agent-plan/../runs").status_code == 404
    assert api.get(f"/api/trips/{TRIP}/multi-agent-plan/magent_XYZ").status_code == 422
    cross = api.post(
        f"/api/trips/{OTHER_TRIP}/multi-agent-plan/{run_id}/review",
        json={"decision": "approve"},
    )
    assert cross.status_code == 404
    assert multi_agent.review_calls() == []
    assert multi_agent.runs[run_id]["status"] == "awaiting_human"


def test_approve_saves_every_item_through_the_itinerary_rules(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)

    response = review(api, run_id, decision="approve", notes="Looks right")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["persistence"]["outcome"] == "saved"
    assert [item["id"] for item in data["persistence"]["saved"]] == [
        f"item_{run_id}_0",
        f"item_{run_id}_1",
    ]
    saved = plan_items(database_api, run_id)
    assert saved[f"item_{run_id}_0"]["trip_id"] == TRIP
    assert saved[f"item_{run_id}_0"]["notes"] == (
        f"Added from multi-agent plan {run_id} (source act_opera)."
    )
    assert multi_agent.review_calls() == [
        {"decision": "approve", "reviewer": "traveller", "notes": "Looks right"}
    ]
    # The approved items do not clash with themselves once saved.
    assert all(item["warnings"] == [] for item in data["approved_items"])


def test_approve_is_refused_before_recording_when_an_item_cannot_be_saved(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent, [ITEMS[0], draft(date="2027-05-09")])
    before = deepcopy(database_api.items)

    response = review(api, run_id, decision="approve")

    assert response.status_code == 422
    assert response.json()["error"]["details"] == [
        {
            "field": "items.1",
            "issue": "date must fall between 2027-04-01 and 2027-04-03",
        }
    ]
    assert multi_agent.review_calls() == []
    assert multi_agent.runs[run_id]["status"] == "awaiting_human"
    assert database_api.items == before


def test_reject_records_the_decision_and_saves_nothing(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)
    before = deepcopy(database_api.items)

    response = review(api, run_id, decision="reject", notes="Not this trip")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "rejected"
    assert data["persistence"] == {
        "outcome": "rejected",
        "saved": [],
        "already_saved": [],
        "failed": [],
    }
    assert database_api.items == before
    assert review(api, run_id, decision="reject").status_code == 200
    assert database_api.items == before


def test_partial_saves_only_the_selected_items(api, multi_agent, database_api) -> None:
    run_id = awaiting(api, multi_agent, [*ITEMS, draft(date="2027-05-09")])

    out_of_range = review(api, run_id, decision="partial", accepted_items=[0, 7])
    unsaveable = review(api, run_id, decision="partial", accepted_items=[2])
    empty = review(api, run_id, decision="partial", accepted_items=[])
    assert [out_of_range.status_code, unsaveable.status_code, empty.status_code] == [
        422,
        422,
        422,
    ]
    assert multi_agent.review_calls() == []

    response = review(api, run_id, decision="partial", accepted_items=[1, 1])

    assert response.status_code == 200
    assert multi_agent.review_calls()[-1]["accepted_actions"] == [1]
    assert list(plan_items(database_api, run_id)) == [f"item_{run_id}_1"]
    assert database_api.items[f"item_{run_id}_1"]["title"] == "Breakfast"


def test_correct_saves_the_human_version_and_bad_corrections_change_nothing(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)
    before = deepcopy(database_api.items)

    for bad in (
        [draft(date="2027-05-09")],
        [draft(start_time="17:00", end_time="16:00")],
        [draft(title="")],
        [],
    ):
        response = review(api, run_id, decision="correct", corrected_items=bad)
        assert response.status_code == 422
    assert multi_agent.review_calls() == []
    assert database_api.items == before

    corrected = draft(start_time="15:00", end_time="17:00", title="Later tour")
    response = review(api, run_id, decision="correct", corrected_items=[corrected])

    assert response.status_code == 200, response.text
    sent = multi_agent.review_calls()[-1]["corrected_result"]
    assert sent == {"summary": "Two days planned.", "items": [corrected]}
    saved = plan_items(database_api, run_id)
    assert list(saved) == [f"item_{run_id}_0"]
    assert saved[f"item_{run_id}_0"]["title"] == "Later tour"
    assert saved[f"item_{run_id}_0"]["start_time"] == "15:00"
    data = response.json()["data"]
    assert data["summary"] == "Two days planned."
    assert data["approved_items"][0]["title"] == "Later tour"


def test_repeating_a_decision_does_not_write_twice_or_change_it(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)
    assert review(api, run_id, decision="approve").status_code == 200
    count = len(database_api.items)

    again = review(api, run_id, decision="approve")
    other = review(api, run_id, decision="reject")

    assert again.status_code == 200
    persistence = again.json()["data"]["persistence"]
    assert persistence["outcome"] == "saved"
    assert persistence["saved"] == []
    assert len(persistence["already_saved"]) == 2
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "MULTI_AGENT_ALREADY_DECIDED"
    assert len(database_api.items) == count
    assert len(multi_agent.review_calls()) == 1


def test_a_concurrent_decision_is_honoured_not_overwritten(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)
    multi_agent.decide_before_review = "reject"

    response = review(api, run_id, decision="approve")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MULTI_AGENT_ALREADY_DECIDED"
    assert plan_items(database_api, run_id) == {}


def test_partial_save_failure_is_reported_and_retry_completes_it(
    client_factory, database_api, multi_agent
) -> None:
    fail_breakfast = {"remaining": 1}

    def flaky_database(request: httpx.Request) -> httpx.Response:
        if (
            request.method == "POST"
            and request.url.path.endswith("/itinerary-items")
            and b"Breakfast" in request.content
            and fail_breakfast["remaining"]
        ):
            fail_breakfast["remaining"] -= 1
            return error_response(503, "DATABASE_BUSY", "The database is busy.")
        return database_api.handle(request)

    with client_factory(
        flaky_database,
        settings_override=ENABLED,
        multi_agent_handler=multi_agent.handle,
    ) as api:
        run_id = awaiting(api, multi_agent)
        first = review(api, run_id, decision="approve").json()["data"]
        status = api.get(f"/api/trips/{TRIP}/multi-agent-plan/{run_id}").json()
        retry = review(api, run_id, decision="approve").json()["data"]

    assert first["persistence"]["outcome"] == "partially_saved"
    assert [item["index"] for item in first["persistence"]["saved"]] == [0]
    assert first["persistence"]["failed"] == [
        {
            "index": 1,
            "id": f"item_{run_id}_1",
            "code": "DATABASE_BUSY",
            "message": "The database is busy.",
        }
    ]
    assert status["data"]["persistence"]["outcome"] == "partially_saved"
    assert status["data"]["persistence"]["failed"][0]["code"] == "NOT_SAVED"
    assert retry["persistence"]["outcome"] == "saved"
    assert [item["index"] for item in retry["persistence"]["saved"]] == [1]
    assert [item["index"] for item in retry["persistence"]["already_saved"]] == [0]
    assert len(plan_items(database_api, run_id)) == 2
    assert len(multi_agent.review_calls()) == 1


def test_an_id_taken_on_another_trip_is_a_failure_not_a_save(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)
    database_api.items[f"item_{run_id}_0"] = {
        **database_api.items["item_2027_sydney_dinner"],
        "id": f"item_{run_id}_0",
        "trip_id": OTHER_TRIP,
    }

    data = review(api, run_id, decision="approve").json()["data"]

    assert data["persistence"]["outcome"] == "partially_saved"
    assert data["persistence"]["failed"][0]["code"] == "CONFLICT"
    assert database_api.items[f"item_{run_id}_0"]["trip_id"] == OTHER_TRIP


@pytest.mark.parametrize("status", ["working", "failed"])
def test_a_run_not_awaiting_review_cannot_take_a_decision(
    api, multi_agent, status
) -> None:
    run_id = start(api)["run_id"]
    multi_agent.runs[run_id]["status"] = status

    response = review(api, run_id, decision="approve")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MULTI_AGENT_NOT_REVIEWABLE"
    assert multi_agent.review_calls() == []


def test_malformed_approved_actions_are_not_saved(
    api, multi_agent, database_api
) -> None:
    run_id = awaiting(api, multi_agent)
    multi_agent.runs[run_id].update(
        status="completed",
        human={
            "decision": "approve",
            "reviewer": "traveller",
            "decided_at": NOW,
            "accepted_actions": [0],
        },
        approved_actions=[{"title": "no date"}],
    )

    data = review(api, run_id, decision="approve").json()["data"]

    assert data["persistence"]["outcome"] == "nothing_saved"
    assert data["persistence"]["failed"][0]["code"] == "VALIDATION_ERROR"
    assert plan_items(database_api, run_id) == {}


def test_settings_read_the_multi_agent_environment(monkeypatch) -> None:
    monkeypatch.setenv("STUDENT1_BACKEND_MULTI_AGENT_ENABLED", "true")
    monkeypatch.setenv(
        "STUDENT1_BACKEND_MULTI_AGENT_BASE_URL", "http://host.docker.internal:8013/"
    )
    monkeypatch.setenv("STUDENT1_BACKEND_MULTI_AGENT_TIMEOUT_SECONDS", "9")

    settings = Settings.from_env()

    assert settings.multi_agent_enabled is True
    assert settings.multi_agent_base_url == "http://host.docker.internal:8013"
    assert settings.multi_agent_timeout_seconds == 9.0
    monkeypatch.delenv("STUDENT1_BACKEND_MULTI_AGENT_ENABLED")
    assert Settings.from_env().multi_agent_enabled is False
