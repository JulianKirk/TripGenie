from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, DETAIL
from tests.frontend.test_planner import RUN, response_data


def card_response() -> dict[str, Any]:
    data = response_data()
    data["answer"]["parts"].append({"type": "activity", "activity_id": ACTIVITY_ID})
    data["answer"]["activities"] = {ACTIVITY_ID: DETAIL}
    return data


def test_dismissal_hides_card_and_narrative_but_keeps_restore_and_selection() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=card_response()))
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.get(f"/planner/{RUN}?selection=1")
    assert "Sydney Harbour guided walk</h3>" not in response.text
    assert '<p class="assistant-text">Take a walk.</p>' not in response.text
    assert "Restore all suggestions" in response.text
    assert 'name="selection" value="1"' in response.text
    assert "No activities selected" in response.text


def test_approval_submits_selected_card_trip_and_schedule() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_data("completed"))

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        client.post(
            f"/planner/{RUN}/review",
            data={
                "decision": "approve",
                "reviewer": "Alex",
                "selection": "1",
                "selected_ids": ACTIVITY_ID,
                "trip_id": "trip_sydney",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:00",
            },
        )
    payload = json.loads(requests[0].content)
    assert payload["trip_id"] == "trip_sydney"
    assert payload["selections"] == [
        {"activity_id": ACTIVITY_ID, "date": "2027-04-02", "start_time": "09:00"}
    ]


def test_regeneration_requires_feedback_and_uses_separate_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202 if request.method == "POST" else 200, json=response_data("planning")
        )

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            f"/planner/{RUN}/regenerate",
            data={"reviewer": "Alex", "feedback": "Prefer indoor activities"},
        )
    assert requests[0].url.path == f"/activity/planner/runs/{RUN}/regenerate"
    assert json.loads(requests[0].content)["feedback"] == "Prefer indoor activities"
    assert "every 2s" in response.text


def test_partial_add_failures_are_visible_and_do_not_replay_writes() -> None:
    data = card_response()
    data["run"]["status"] = "completed"
    data["save_errors"] = [
        {
            "activity_id": ACTIVITY_ID,
            "trip_id": "trip_sydney",
            "message": "Trip service unavailable",
        }
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=data)

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(f"/planner/{RUN}")
    assert "Trip service unavailable" in response.text
    assert "Add to itinerary" in response.text
    assert all(request.method == "GET" for request in requests)


def test_unknown_query_ids_cannot_become_visible_or_approved_suggestions() -> None:
    forged = "0f2b1c4e-aaaa-bbbb-cccc-000000000099"
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=card_response()))
    with TestClient(create_app(Settings(), transport=transport)) as client:
        response = client.get(f"/planner/{RUN}?selection=1&selected_ids={forged}")
    assert forged not in response.text
    assert "No activities selected" in response.text
    assert 'value="approve" disabled' in response.text


def test_trip_directory_and_schedule_fields_are_loaded_for_grounded_cards() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
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
        return httpx.Response(200, json=card_response())

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(f"/planner/{RUN}")
    assert "Sydney holiday" in response.text
    assert f'name="date_{ACTIVITY_ID}"' in response.text
    assert f'name="start_time_{ACTIVITY_ID}"' in response.text
    assert "Approve and add to trip" in response.text
    assert "Dismiss suggestion" in response.text


def test_regeneration_missing_feedback_never_posts_and_preserves_selection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/activity/trips":
            return httpx.Response(200, json={"available": False, "trips": []})
        return httpx.Response(200, json=card_response())

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            f"/planner/{RUN}/regenerate",
            data={
                "reviewer": "Alex",
                "feedback": " ",
                "selection": "1",
                "trip_id": "trip_sydney",
            },
        )
    assert all(request.method == "GET" for request in requests)
    assert "Enter your name and feedback" in response.text
    assert "No activities selected" in response.text
    assert 'value="Alex"' in response.text


def test_lost_regeneration_response_never_replays_and_keeps_feedback() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            message = "Lost response"
            raise httpx.ReadTimeout(message, request=request)
        return httpx.Response(200, json=response_data("rejected"))

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            f"/planner/{RUN}/regenerate",
            data={
                "reviewer": "Alex",
                "feedback": "More indoor options",
            },
        )
    assert [request.method for request in requests] == ["POST", "GET"]
    assert "More indoor options" in response.text
    assert "disabled>Reject and regenerate" in response.text


def test_recovery_retains_trip_and_schedule_without_resending_review() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/activity/trips":
            return httpx.Response(200, json={"available": False, "trips": []})
        return httpx.Response(200, json=card_response())

    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            f"/planner/{RUN}/recover",
            data={
                "reviewer": "Alex",
                "selection": "1",
                "selected_ids": ACTIVITY_ID,
                "trip_id": "trip_sydney",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:15",
            },
        )
    assert all(request.method == "GET" for request in requests)
    assert 'value="2027-04-02"' in response.text
    assert 'value="09:15"' in response.text
    assert 'value="trip_sydney" selected' in response.text
    assert "added activities to your trip" in response.text


def test_dismiss_and_restore_preserve_typed_review_without_sending_a_decision() -> None:
    requests: list[httpx.Request] = []
    other = "0f2b1c4e-aaaa-bbbb-cccc-000000000005"
    data = card_response()
    data["answer"]["parts"].append({"type": "activity", "activity_id": other})
    data["answer"]["activities"][other] = {**DETAIL, "id": other, "name": "Other walk"}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/activity/trips":
            return httpx.Response(200, json={"available": False, "trips": []})
        return httpx.Response(200, json=data)

    fields = {
        "reviewer": "Alex",
        "notes": "Preserve notes",
        "correction": "Edited prose",
        "selection": "1",
        "selected_ids": [ACTIVITY_ID, other],
        "activity_ids": [ACTIVITY_ID, other],
        "trip_id": "trip_sydney",
        f"date_{other}": "2027-04-02",
        f"start_time_{other}": "09:15",
    }
    with TestClient(
        create_app(Settings(), transport=httpx.MockTransport(handler))
    ) as client:
        dismissed = client.post(
            f"/planner/{RUN}/selection", data={**fields, "dismiss_id": ACTIVITY_ID}
        )
        assert "Sydney Harbour guided walk</h3>" not in dismissed.text
        assert "Other walk</h3>" in dismissed.text
        assert 'value="Alex"' in dismissed.text
        assert "Preserve notes" in dismissed.text
        assert "Edited prose" in dismissed.text
        assert 'value="09:15"' in dismissed.text
        assert "selected_ids=" + other in dismissed.headers["HX-Push-Url"]
        restored = client.post(
            f"/planner/{RUN}/selection",
            data={**fields, "selected_ids": other, "restore": "all"},
        )
    assert "Sydney Harbour guided walk</h3>" in restored.text
    assert 'value="09:15"' in restored.text
    assert all(request.method == "GET" for request in requests)


def test_polling_before_results_does_not_dismiss_future_cards() -> None:
    data = response_data("planning")
    with TestClient(
        create_app(
            Settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
        )
    ) as client:
        page = client.get(f"/planner/{RUN}", headers={"HX-Request": "true"})
    assert f'hx-get="/planner/{RUN}"' in page.text
    assert "selection=1" not in page.text


def test_regeneration_moves_browser_to_new_run_and_preserves_parent_on_poll() -> None:
    child = "magent_aaaaaaaaaaaa"
    data = response_data("planning")
    data["run"]["run_id"] = child
    data["previous_run_id"] = RUN
    with TestClient(
        create_app(
            Settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(202, json=data)),
        )
    ) as client:
        response = client.post(
            f"/planner/{RUN}/regenerate",
            data={"reviewer": "Alex", "feedback": "Indoor instead"},
            headers={"HX-Request": "true"},
        )
    expected = f"/planner/{child}?previous_run_id={RUN}"
    assert response.headers.get("HX-Push-Url") == expected
    assert f'hx-get="{expected}"' in response.text


def test_approved_subset_hides_unchanged_original_narrative() -> None:
    data = card_response()
    parts = data["answer"]["parts"]
    data["run"].update(
        status="completed",
        result={
            "type": "final",
            "parts": [
                *parts,
                {
                    "type": "activity",
                    "activity_id": "00000000-0000-0000-0000-000000000099",
                },
            ],
        },
        final_result={"type": "final", "parts": parts},
    )
    with TestClient(
        create_app(
            Settings(),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
        )
    ) as client:
        response = client.get(f"/planner/{RUN}")
    assert "Take a walk." not in response.text
    assert DETAIL["name"] in response.text
