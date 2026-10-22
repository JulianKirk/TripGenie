from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID
from tests.frontend.test_planner import RUN
from tests.frontend.test_planner_items import OTHER, cards, handler_for


def test_unresolved_suggestions_cannot_be_applied() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/review",
            data={
                "reviewer": "Alex",
                f"choice_{ACTIVITY_ID}": "approve",
                "trip_id": "trip_sydney",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:30",
            },
            headers={"HX-Request": "true"},
        )
    assert "every suggestion" in page.text
    assert all(r.method == "GET" for r in requests)
    assert "✓ Approved · pending" in page.text


def test_all_rejected_applies_without_trip_or_schedule() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        client.post(
            f"/planner/{RUN}/review",
            data={
                "reviewer": "Alex",
                f"choice_{ACTIVITY_ID}": "reject",
                f"choice_{OTHER}": "reject",
            },
            headers={"HX-Request": "true"},
        )
    posts = [r for r in requests if r.method == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    assert body["decision"] == "reject" and "trip_id" not in body
    assert "selections" not in body


def test_unknown_staged_id_cannot_create_a_suggestion_or_a_write() -> None:
    requests: list[httpx.Request] = []
    forged = "00000000-0000-0000-0000-000000000099"
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={"approve_id": forged},
            headers={"HX-Request": "true"},
        )
    assert "Choose an activity from this result" in page.text
    assert forged not in page.text
    assert all(r.method == "GET" for r in requests)


def test_failed_checks_disable_approval_but_allow_rejection() -> None:
    data = cards()
    data["run"]["checks"][0]["passed"] = False
    with TestClient(create_app(Settings(), transport=handler_for(data, []))) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert " disabled>Approve</button>" in page.text
    assert ">Reject</button>" in page.text
    assert " disabled>Reject</button>" not in page.text


def test_lost_apply_response_reads_authoritative_status_without_replay() -> None:
    requests: list[httpx.Request] = []
    data = cards()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            data["run"]["status"] = "completed"
            data["run"]["human"] = {"decision": "correct", "reviewer": "Alex"}
            data["item_decisions"] = [
                {"activity_id": ACTIVITY_ID, "decision": "approve"},
                {"activity_id": OTHER, "decision": "reject"},
            ]
            message = "Lost response"
            raise httpx.ReadTimeout(message, request=request)
        if request.url.path == "/activity/trips":
            return httpx.Response(200, json={"available": False, "trips": []})
        return httpx.Response(200, json=data)

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/review",
            data={
                "reviewer": "Alex",
                f"choice_{ACTIVITY_ID}": "approve",
                f"choice_{OTHER}": "reject",
                "trip_id": "trip_sydney",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:30",
            },
            headers={"HX-Request": "true"},
        )
    assert sum(r.method == "POST" for r in requests) == 1
    assert "Human decisions recorded" in page.text
    assert "Add to itinerary" not in page.text
    assert ">Apply approvals<" not in page.text


def test_refresh_query_restores_planner_in_main_assistant_panel() -> None:
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), []))
    ) as client:
        page = client.get(f"/?planner_run={RUN}")
    assert page.status_code == 200
    assert "AI activity assistant" in page.text
    assert 'value="planner" checked' in page.text
    assert 'id="activity-results"' in page.text


def test_tool_dropdown_rejects_foreign_or_invalid_structured_rows() -> None:
    data = cards("reviewing")
    data["answer"]["tools"] = [
        {
            "tool": "activities_search",
            "status": "success",
            "duration_ms": 1,
            "arguments": {},
            "result": {
                "structuredContent": {
                    "source": "student-3",
                    "ok": True,
                    "data": {"items": [{"id": ACTIVITY_ID, "name": "Wrong source"}]},
                }
            },
        }
    ]
    with TestClient(create_app(Settings(), transport=handler_for(data, []))) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert "Activities found · 0" in page.text


def test_result_without_cards_can_be_rejected_and_closed() -> None:
    from tests.frontend.test_planner import response_data

    requests: list[httpx.Request] = []
    data = response_data()
    with TestClient(
        create_app(Settings(), transport=handler_for(data, requests))
    ) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
        assert "Reject result</button>" in page.text
        client.post(
            f"/planner/{RUN}/review",
            data={"reviewer": "Alex", "result_reason": "No usable activities"},
            headers={"HX-Request": "true"},
        )
    posts = [request for request in requests if request.method == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0].content) == {
        "decision": "reject",
        "reviewer": "Alex",
        "notes": "No usable activities",
    }
