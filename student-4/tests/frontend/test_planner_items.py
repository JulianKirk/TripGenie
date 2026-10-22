from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, DETAIL, FakeBackend
from tests.frontend.test_planner import RUN, response_data

OTHER = "0f2b1c4e-aaaa-bbbb-cccc-000000000005"


def cards(status: str = "awaiting_human") -> dict[str, Any]:
    data = response_data(status)
    data["answer"]["parts"] += [
        {"type": "activity", "activity_id": ACTIVITY_ID},
        {"type": "activity", "activity_id": OTHER},
    ]
    data["answer"]["activities"] = {
        ACTIVITY_ID: DETAIL,
        OTHER: {**DETAIL, "id": OTHER, "name": "Another walk"},
    }
    data["run"]["checks"] = [
        {"name": "grounding", "passed": True, "blocking": True, "detail": "Grounded"}
    ]
    return data


def handler_for(
    data: dict[str, Any], requests: list[httpx.Request]
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.startswith("/activity/planner/runs"):
            return httpx.Response(200, json=data)
        if request.url.path == "/activity/trips":
            return httpx.Response(
                200,
                json={
                    "available": True,
                    "trips": [
                        {
                            "id": "trip_sydney",
                            "name": "Sydney holiday",
                            "destination": "Sydney",
                            "start_date": "2027-04-01",
                            "end_date": "2027-04-03",
                            "traveller_count": 2,
                            "status": "planned",
                        }
                    ],
                },
            )
        return FakeBackend._default_response(request)

    return httpx.MockTransport(handle)


def test_inline_workflow_orders_evidence_checks_and_single_review_cards() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.get(f"/planner/{RUN}")
    assert "AI activity assistant" in page.text
    assert 'value="planner" checked' in page.text
    assert page.text.index('id="planner-stage-worker"') < page.text.index(
        "Validation checks"
    )
    assert page.text.index("Validation checks") < page.text.index(
        "Sydney Harbour guided walk</h3>"
    )
    assert page.text.count("Sydney Harbour guided walk</h3>") == 1
    assert page.text.count(">Approve</button>") == 2
    assert page.text.count(">Reject</button>") == 2
    assert "Reject without reason</button>" not in page.text
    assert "Restore all suggestions" not in page.text
    assert "Reject and regenerate" not in page.text
    assert "Add to itinerary" not in page.text


def test_running_workflow_has_evidence_dropdowns_but_no_review_cards() -> None:
    data = cards("reviewing")
    data["answer"]["tools"] = [
        {
            "tool": "activities_search",
            "status": "success",
            "duration_ms": 3,
            "arguments": {},
            "result": {
                "structuredContent": {
                    "ok": True,
                    "source": "student-4",
                    "data": {
                        "items": [
                            {"id": ACTIVITY_ID, "name": "Sydney Harbour guided walk"}
                        ]
                    },
                }
            },
        }
    ]
    with TestClient(create_app(Settings(), transport=handler_for(data, []))) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert "Activities found · 1" in page.text
    assert "Tools used · 1 calls" in page.text
    assert "Sydney Harbour guided walk" in page.text
    assert "activity-card" not in page.text
    assert ">Approve</button>" not in page.text
    assert "every 2s" in page.text


def test_staging_approval_only_reads_and_shows_pending_symbol() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={
                "approve_id": ACTIVITY_ID,
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:15",
                "reviewer": "Alex",
                f"trip_{ACTIVITY_ID}": "trip_sydney",
            },
            headers={"HX-Request": "true"},
        )
    assert all(r.method == "GET" for r in requests)
    assert "✓ Approved · pending" in page.text
    assert "1 of 2 suggestions reviewed" in page.text
    assert 'name="choice_' + ACTIVITY_ID + '" value="approve"' in page.text
    assert "Another walk</h3>" in page.text
    assert 'value="Alex"' in page.text


def test_reject_without_reason_keeps_red_card_and_clears_old_reason() -> None:
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), []))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={
                "reject_id": ACTIVITY_ID,
                f"reason_{ACTIVITY_ID}": "",
            },
            headers={"HX-Request": "true"},
        )
    assert 'class="activity-card activity-card--rejected"' in page.text
    assert "Sydney Harbour guided walk</h3>" in page.text
    assert "Rejected · pending" in page.text and "no reason supplied" in page.text
    assert "Old reason" not in page.text


def test_blank_rejection_reason_stages_without_sending_a_decision() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={
                "reject_reason_id": ACTIVITY_ID,
                f"reason_{ACTIVITY_ID}": "  ",
                "reviewer": "Alex",
            },
            headers={"HX-Request": "true"},
        )
    assert all(r.method == "GET" for r in requests)
    assert "no reason supplied" in page.text
    assert 'value="Alex"' in page.text


def test_rejection_with_reason_keeps_other_pending_choices_and_schedule() -> None:
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), []))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={
                "reject_reason_id": OTHER,
                f"reason_{OTHER}": "Too strenuous <script>bad</script>",
                f"choice_{ACTIVITY_ID}": "approve",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:15",
                f"trip_{ACTIVITY_ID}": "trip_sydney",
            },
            headers={"HX-Request": "true"},
        )
    assert "Too strenuous &lt;script&gt;bad&lt;/script&gt;" in page.text
    assert "2 of 2 suggestions reviewed · 1 approved · 1 rejected" in page.text
    assert 'value="2027-04-02"' in page.text and 'value="09:15"' in page.text
    assert 'value="trip_sydney"' in page.text
    assert "Apply approvals</button>" in page.text


def test_apply_sends_all_choices_but_only_approved_schedule_once() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/review",
            data={
                f"choice_{ACTIVITY_ID}": "approve",
                f"choice_{OTHER}": "reject",
                f"reason_{OTHER}": "Too strenuous",
                "reviewer": "Alex",
                f"trip_{ACTIVITY_ID}": "trip_sydney",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:15",
            },
            headers={"HX-Request": "true"},
        )
    posts = [r for r in requests if r.method == "POST"]
    assert len(posts) == 1 and page.status_code == 200
    assert posts[0].url.path.endswith("/review")
    assert json.loads(posts[0].content) == {
        "decision": "approve",
        "reviewer": "Alex",
        "selections": [
            {
                "activity_id": ACTIVITY_ID,
                "trip_id": "trip_sydney",
                "date": "2027-04-02",
                "start_time": "09:15",
            }
        ],
        "item_decisions": [
            {
                "activity_id": ACTIVITY_ID,
                "decision": "approve",
                "notes": None,
                "trip_id": "trip_sydney",
                "date": "2027-04-02",
                "start_time": "09:15",
            },
            {"activity_id": OTHER, "decision": "reject", "notes": "Too strenuous"},
        ],
    }


def test_recorded_mixed_choices_keep_all_cards_with_final_symbols() -> None:
    data = cards("completed")
    data["run"]["human"] = {"decision": "correct", "reviewer": "Alex"}
    data["item_decisions"] = [
        {"activity_id": ACTIVITY_ID, "decision": "approve"},
        {"activity_id": OTHER, "decision": "reject", "notes": "Too strenuous"},
    ]
    with TestClient(create_app(Settings(), transport=handler_for(data, []))) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert "Sydney Harbour guided walk</h3>" in page.text
    assert "Another walk</h3>" in page.text
    assert "✓ Approved</strong>" in page.text and "Too strenuous" in page.text
    assert "Human decisions recorded" in page.text
    assert "· pending" not in page.text and ">Apply approvals<" not in page.text
    assert "Take a walk." not in page.text


def test_all_agent_dropdowns_are_present_before_execution() -> None:
    with TestClient(
        create_app(Settings(), transport=handler_for(cards("planning"), []))
    ) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert 'id="planner-stage-planner"' in page.text
    assert 'id="planner-stage-worker"' in page.text
    assert 'id="planner-stage-reviewer"' in page.text
    assert page.text.count("Not yet run</span>") == 3
    assert "Running</span>" in page.text
    assert "Agent execution</summary>" not in page.text


def test_worker_contains_activity_and_tool_submenus_and_retry_statuses() -> None:
    data = cards("working")
    data["run"]["attempts"] = 2
    data["run"]["steps"] = [
        {"agent": "planner", "attempt": 1, "status": "completed"},
        {"agent": "worker", "attempt": 1, "status": "failed"},
        {"agent": "reviewer", "attempt": 1, "status": "completed"},
        {"agent": "planner", "attempt": 2, "status": "completed"},
    ]
    with TestClient(create_app(Settings(), transport=handler_for(data, []))) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    worker = page.text.split('id="planner-stage-worker"')[1].split(
        'id="planner-stage-reviewer"'
    )[0]
    reviewer = page.text.split('id="planner-stage-reviewer"')[1]
    assert "Running</span>" in worker
    assert "Activities found" in worker and "Tools used" in worker
    assert "Not yet run</span>" in reviewer
    assert "attempt 1 · failed" in worker


def test_timeout_marks_the_interrupted_agent_failed_without_a_finished_step() -> None:
    for finished, interrupted in (
        ([], "planner"),
        (["planner"], "worker"),
        (["planner", "worker"], "reviewer"),
        (["planner", "worker", "reviewer"], "planner"),
    ):
        data = cards("failed")
        data["run"]["error"] = {"code": "RUN_TIMEOUT", "message": "Workflow timed out"}
        data["run"]["steps"] = [
            {"agent": name, "attempt": 1, "status": "completed"} for name in finished
        ]
        with TestClient(
            create_app(Settings(), transport=handler_for(data, []))
        ) as client:
            page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
        stage = page.text.split(f'id="planner-stage-{interrupted}"')[1].split(
            "</summary>"
        )[0]
        assert 'planner-status--failed">Failed</span>' in stage
