from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

RUN = "magent_0123456789ab"


def response_data(status: str = "awaiting_human") -> dict[str, Any]:
    return {
        "run": {
            "run_id": RUN,
            "feature": "student-4",
            "task": "Find a walk",
            "status": status,
            "plan": {"goal": "<script>bad</script>", "steps": ["Search activities"]},
            "review": {"verdict": "approve", "summary": "Suitable options"},
            "steps": [],
            "checks": [],
        },
        "answer": {
            "request_id": RUN,
            "status": "complete",
            "parts": [{"type": "text", "text": "Take a walk."}],
            "tools": [],
        },
    }


def test_start_planner_uses_own_backend_and_polls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json=response_data("planning"))

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            "/suggestions/ask",
            data={
                "mode": "planner",
                "question": "Find a walk",
                "trip_id": "trip_sydney",
            },
            headers={"HX-Request": "true"},
        )
    assert requests[0].url.path == "/activity/planner/runs"
    assert json.loads(requests[0].content)["trip_id"] == "trip_sydney"
    assert "every 2s" in response.text
    assert f"/planner/{RUN}" in response.text
    assert "<script>bad</script>" not in response.text


def test_awaiting_review_stops_polling_and_offers_human_controls() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response_data()))
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.get(f"/planner/{RUN}")
    assert response.status_code == 200
    assert "<html" in response.text
    assert "every 2s" not in response.text
    assert "Approve" in response.text and "Reject" in response.text
    assert "Save correction" in response.text
    assert "Suitable options" in response.text
    assert "&lt;script&gt;bad&lt;/script&gt;" in response.text


def test_correction_submits_edited_result_not_another_ai_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_data("completed"))

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            f"/planner/{RUN}/review",
            data={
                "decision": "correct",
                "reviewer": "Julian",
                "correction": "Keep it short.",
            },
        )
    assert response.status_code == 200
    body = json.loads(requests[0].content)
    assert body["corrected_result"] == {
        "type": "final",
        "parts": [{"type": "text", "text": "Keep it short."}],
    }
    assert requests[0].url.path == f"/activity/planner/runs/{RUN}/review"


def test_disabled_planner_explains_failure_without_hiding_other_modes() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(503, json={"detail": "Smart Planner is disabled."})
    )
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.post(
            "/suggestions/ask", data={"mode": "planner", "question": "Find a walk"}
        )
    assert "Smart Planner is disabled." in response.text
    assert "Smart Planner unavailable" in response.text


def test_polling_cards_keep_the_dialog_target_and_hide_draft_itinerary_action() -> None:
    from tests.frontend.conftest import ACTIVITY_ID, DETAIL

    data = response_data("reviewing")
    data["answer"]["parts"].append({"type": "activity", "activity_id": ACTIVITY_ID})
    data["answer"]["activities"] = {ACTIVITY_ID: DETAIL}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert "Sydney Harbour guided walk" in response.text
    assert 'hx-target="#activity-dialog" hx-swap="innerHTML"' in response.text
    assert "Add to itinerary" not in response.text


def test_evidence_download_contains_run_and_events() -> None:
    data = {
        "run": response_data()["run"],
        "history": [
            {
                "sequence": 1,
                "run_id": RUN,
                "at": "2026-10-21T00:00:00Z",
                "actor": "human:Julian",
                "event": "human_decision",
                "detail": {},
            }
        ],
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.get(f"/planner/{RUN}/history")
    assert (
        response.headers["content-disposition"] == f'attachment; filename="{RUN}.json"'
    )
    assert response.json()["history"][0]["actor"] == "human:Julian"
