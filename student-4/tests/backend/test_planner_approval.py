from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

from tests.backend.test_activity_api import (
    ACTIVITY_ID,
    FakeDatabase,
    location_handler,
    public_payload,
)
from tests.backend.test_itinerary_api import SYDNEY, FakeItinerary
from tests.backend.test_planner import PATH, RUN, record

OTHER = "00000000-0000-0000-0000-000000000002"


def grounded() -> dict[str, Any]:
    return record(
        trip_id=SYDNEY,
        result={
            "type": "final",
            "parts": [
                {"type": "text", "text": "Try these."},
                {"type": "activity", "activity_id": ACTIVITY_ID},
                {"type": "activity", "activity_id": OTHER},
            ],
        },
        steps=[
            {
                "agent": "worker",
                "attempt": 1,
                "status": "completed",
                "tools": [
                    {
                        "tool": "activities_search",
                        "arguments": {},
                        "status": "success",
                        "duration_ms": 1,
                        "result": {
                            "structuredContent": {
                                "source": "student-4",
                                "ok": True,
                                "data": {"items": [{"id": ACTIVITY_ID}, {"id": OTHER}]},
                            }
                        },
                    }
                ],
            }
        ],
    )


class Workflow:
    def __init__(self) -> None:
        self.run = grounded()
        self.posts: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            self.posts.append(body)
            if request.url.path == "/runs":
                return httpx.Response(
                    202,
                    json={
                        "data": record(
                            run_id="magent_aaaaaaaaaaaa", status="planning", result=None
                        )
                    },
                )
            self.run.update(
                status="rejected" if body["decision"] == "reject" else "completed",
                final_result=body.get("corrected_result", self.run["result"]),
                human={"decision": body["decision"], "reviewer": body["reviewer"]},
            )
        return httpx.Response(200, json={"data": self.run})


def app(workflow: Workflow, itinerary: FakeItinerary) -> TestClient:
    return TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(workflow.handle),
            itinerary_transport=httpx.MockTransport(itinerary.handle),
            database_transport=httpx.MockTransport(FakeDatabase().handle),
            location_transport=httpx.MockTransport(location_handler),
        )
    )


def test_subset_approval_adds_only_selected_after_shared_completion() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [
                    {
                        "activity_id": ACTIVITY_ID,
                        "date": "2027-04-02",
                        "start_time": "09:30",
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["saved"] == [
            {"activity_id": ACTIVITY_ID, "trip_id": SYDNEY, "status": "added"}
        ]
        assert (
            client.post(
                f"{PATH}/review", json={"decision": "approve", "reviewer": "Julian"}
            ).status_code
            == 409
        )
    assert workflow.posts[0]["decision"] == "correct"
    assert "selections" not in workflow.posts[0] and "trip_id" not in workflow.posts[0]
    assert [
        p.get("activity_id")
        for p in workflow.posts[0]["corrected_result"]["parts"]
        if p["type"] == "activity"
    ] == [ACTIVITY_ID]
    assert itinerary.rows[(SYDNEY, ACTIVITY_ID)]["start_time"] == "09:30"


def test_cards_need_explicit_selections_and_unknown_cards_cannot_be_added() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        for selections in (
            None,
            [],
            [{"activity_id": "00000000-0000-0000-0000-000000000099"}],
        ):
            response = client.post(
                f"{PATH}/review",
                json={
                    "decision": "approve",
                    "reviewer": "Julian",
                    "selections": selections,
                },
            )
            assert response.status_code == 400
    assert not workflow.posts and not itinerary.rows


def test_regeneration_rejects_previous_and_passes_bounded_feedback() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        response = client.post(
            f"{PATH}/regenerate",
            json={
                "reviewer": "Julian",
                "feedback": "More outdoor options",
                "dismissed_activity_ids": [ACTIVITY_ID],
            },
        )
    assert response.status_code == 202, response.text
    assert response.json()["previous_run_id"] == RUN
    assert workflow.posts[0] == {
        "decision": "reject",
        "reviewer": "Julian",
        "notes": "More outdoor options",
    }
    assert workflow.posts[1]["task"] == grounded()["task"]
    assert workflow.posts[1]["context"] == {
        "human_feedback": "More outdoor options",
        "previous_run_id": RUN,
        "rejected_activity_ids": sorted([ACTIVITY_ID, OTHER]),
    }
    assert not itinerary.rows


def test_failed_approval_response_never_writes_and_is_not_retried() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()

    def lost(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            workflow.posts.append(json.loads(request.content))
            msg = "private"
            raise httpx.ReadTimeout(msg)
        return workflow.handle(request)

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(lost),
            itinerary_transport=httpx.MockTransport(itinerary.handle),
            database_transport=httpx.MockTransport(FakeDatabase().handle),
            location_transport=httpx.MockTransport(location_handler),
        )
    ) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [{"activity_id": ACTIVITY_ID}],
            },
        )
    assert response.status_code == 504
    assert len(workflow.posts) == 1 and not itinerary.rows


def test_existing_membership_is_preserved_without_rescheduling() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    itinerary.rows[(SYDNEY, ACTIVITY_ID)] = {
        "trip_id": SYDNEY,
        "activity_id": ACTIVITY_ID,
        "date": "2027-04-01",
        "start_time": "08:00",
    }
    with app(workflow, itinerary) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [
                    {
                        "activity_id": ACTIVITY_ID,
                        "date": "2027-04-02",
                        "start_time": "09:30",
                    }
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["saved"][0]["status"] == "already_present"
    assert itinerary.rows[(SYDNEY, ACTIVITY_ID)]["date"] == "2027-04-01"


def test_invalid_trip_or_schedule_blocks_shared_approval() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        for fields, status in (
            ({"trip_id": "trip_missing"}, 404),
            ({"selections": [{"activity_id": ACTIVITY_ID, "date": "2028-01-01"}]}, 400),
        ):
            body = {
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [{"activity_id": ACTIVITY_ID}],
                **fields,
            }
            assert client.post(f"{PATH}/review", json=body).status_code == status
    assert not workflow.posts and not itinerary.rows


def test_partial_save_failure_is_visible_and_never_retried() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    writes: list[str] = []

    def failed(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            writes.append(request.url.path)
            msg = "private"
            raise httpx.ReadTimeout(msg)
        return itinerary.handle(request)

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(workflow.handle),
            itinerary_transport=httpx.MockTransport(failed),
            database_transport=httpx.MockTransport(FakeDatabase().handle),
            location_transport=httpx.MockTransport(location_handler),
        )
    ) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [{"activity_id": ACTIVITY_ID}],
            },
        )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "completed"
    assert response.json()["saved"] == []
    assert "may have been saved" in response.json()["save_errors"][0]["message"]
    assert len(writes) == 1


def test_regeneration_create_timeout_does_not_retry_and_preserves_rejection() -> None:
    workflow, _itinerary = Workflow(), FakeItinerary()

    def failed(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/runs":
            workflow.posts.append(json.loads(request.content))
            msg = "private"
            raise httpx.ReadTimeout(msg)
        return workflow.handle(request)

    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(failed),
        )
    ) as client:
        response = client.post(
            f"{PATH}/regenerate",
            json={"reviewer": "Julian", "feedback": "Try outdoors"},
        )
        again = client.post(
            f"{PATH}/regenerate",
            json={"reviewer": "Julian", "feedback": "Try outdoors"},
        )
    assert response.status_code == 504
    assert "may have started" in response.json()["detail"]
    assert workflow.run["status"] == "rejected"
    assert len(workflow.posts) == 2 and again.status_code == 409


def test_regeneration_refuses_other_feature_and_blank_feedback() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    workflow.run["feature"] = "student-3"
    with app(workflow, itinerary) as client:
        assert (
            client.post(
                f"{PATH}/regenerate",
                json={"reviewer": "Julian", "feedback": "Try outdoors"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"{PATH}/regenerate", json={"reviewer": "Julian", "feedback": "  "}
            ).status_code
            == 400
        )
    assert not workflow.posts


def test_inactive_suggestion_cannot_be_approved_or_added() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        payload = public_payload()
        payload["is_active"] = False
        assert client.post("/activity", json=payload).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [{"activity_id": ACTIVITY_ID}],
            },
        )
    assert response.status_code == 400
    assert not workflow.posts
    assert not itinerary.rows
