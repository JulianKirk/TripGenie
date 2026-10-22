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
    assert "Smart Planner request failed" in response.text


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


def test_failed_checks_disable_acceptance_but_keep_rejection_available() -> None:
    data = response_data()
    data["run"]["checks"] = [
        {
            "name": "tool_evidence",
            "passed": False,
            "blocking": True,
            "detail": "No tool call succeeded",
        }
    ]
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.get(f"/planner/{RUN}")
    assert 'value="approve" disabled' in response.text
    assert 'value="correct" disabled' in response.text
    assert 'value="reject">Reject' in response.text
    assert "cannot be accepted" in response.text


def test_review_error_preserves_edits_for_html_and_htmx() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(503, json={"detail": "Review unavailable"})
        return httpx.Response(200, json=response_data())

    for headers in ({}, {"HX-Request": "true"}):
        requests.clear()
        with TestClient(
            create_app(Settings(), transport=httpx.MockTransport(handler))
        ) as client:
            response = client.post(
                f"/planner/{RUN}/review",
                data={
                    "decision": "correct",
                    "reviewer": "Alex",
                    "notes": "Keep my notes",
                    "correction": ["First edited paragraph", "Second edited paragraph"],
                    "activity_ids": "0f2b1c4e-aaaa-bbbb-cccc-000000000004",
                },
                headers=headers,
            )
        assert 'value="Alex"' in response.text
        assert "Keep my notes" in response.text
        assert "First edited paragraph" in response.text
        assert "Second edited paragraph" in response.text
        assert 'value="0f2b1c4e-aaaa-bbbb-cccc-000000000004" checked' in response.text
        assert "Review unavailable" in response.text
        assert [r.method for r in requests] == ["POST", "GET"]


def test_unknown_review_outcome_keeps_recovery_form_and_refresh_is_read_only() -> None:
    requests: list[httpx.Request] = []
    available = False

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if not available:
            message = "Lost response"
            raise httpx.ReadTimeout(message, request=request)
        return httpx.Response(200, json=response_data("completed"))

    for headers in ({}, {"HX-Request": "true"}):
        requests.clear()
        available = False
        with TestClient(
            create_app(Settings(), transport=httpx.MockTransport(handler))
        ) as client:
            fields = {
                "decision": "correct",
                "reviewer": "Alex",
                "correction": "My edits",
            }
            response = client.post(
                f"/planner/{RUN}/review", data=fields, headers=headers
            )
            assert "My edits" in response.text
            assert 'value="correct" disabled' in response.text
            assert f"/planner/{RUN}/recover" in response.text
            assert "Refresh progress" not in response.text
            available = True
            refreshed = client.post(
                f"/planner/{RUN}/recover", data=fields, headers=headers
            )
        assert "Accepted" in refreshed.text
        assert "My edits" in refreshed.text
        assert 'value="correct" disabled' in refreshed.text
        assert [r.method for r in requests] == ["POST", "GET", "GET"]


def test_long_valid_narrative_keeps_separate_correction_parts() -> None:
    data = response_data()
    texts = ["A" * 600, "B" * 600]
    data["answer"]["parts"] = [{"type": "text", "text": text} for text in texts]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=data)

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(f"/planner/{RUN}")
        assert response.text.count('name="correction"') == 2
        response = client.post(
            f"/planner/{RUN}/review",
            data={
                "decision": "correct",
                "reviewer": "Alex",
                "correction": texts,
            },
        )
    assert response.status_code == 200
    assert (
        json.loads(requests[-1].content)["corrected_result"]["parts"]
        == data["answer"]["parts"]
    )


def test_correction_total_part_limit_is_checked_without_sending_decision() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_data())

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            f"/planner/{RUN}/review",
            data={
                "decision": "correct",
                "reviewer": "Alex",
                "correction": ["Paragraph"] * 7,
                "activity_ids": [
                    f"0f2b1c4e-aaaa-bbbb-cccc-{index:012d}" for index in range(6)
                ],
            },
        )
    assert "at most twelve" in response.text
    assert 'value="Alex"' in response.text
    assert [r.method for r in requests] == ["GET"]


def test_review_validation_error_keeps_unchecked_cards_and_escaped_fields() -> None:
    from tests.frontend.conftest import ACTIVITY_ID, DETAIL

    other_id = "0f2b1c4e-aaaa-bbbb-cccc-000000000005"
    data = response_data()
    data["answer"]["activities"] = {
        ACTIVITY_ID: DETAIL,
        other_id: {**DETAIL, "id": other_id, "name": "Another walk"},
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=data)

    for headers in ({}, {"HX-Request": "true"}):
        with TestClient(
            create_app(Settings(), transport=httpx.MockTransport(handler))
        ) as client:
            response = client.post(
                f"/planner/{RUN}/review",
                data={
                    "decision": "correct",
                    "reviewer": "",
                    "notes": "<script>bad</script>",
                    "correction": "My draft",
                    "activity_ids": ACTIVITY_ID,
                },
                headers=headers,
            )
        assert 'value="" required' in response.text
        assert "My draft" in response.text
        assert "&lt;script&gt;bad&lt;/script&gt;" in response.text
        assert "<script>bad</script>" not in response.text
        assert f'value="{ACTIVITY_ID}" checked' in response.text
        assert f'value="{other_id}"> Keep Another walk' in response.text
    assert [request.method for request in requests] == ["GET", "GET"]


def test_correction_can_remove_a_text_part_but_not_every_text_part() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_data())

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        client.post(
            f"/planner/{RUN}/review",
            data={
                "decision": "correct",
                "reviewer": "Alex",
                "correction": ["", "Keep this narrative"],
            },
        )
        assert requests[0].method == "POST"
        assert json.loads(requests[0].content)["corrected_result"]["parts"] == [
            {"type": "text", "text": "Keep this narrative"},
        ]
        requests.clear()
        response = client.post(
            f"/planner/{RUN}/review",
            data={
                "decision": "correct",
                "reviewer": "Alex",
                "correction": ["", "  "],
            },
        )
    assert [request.method for request in requests] == ["GET"]
    assert "Enter corrected recommendation text" in response.text
