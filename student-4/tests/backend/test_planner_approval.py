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
                human={
                    "decision": body["decision"],
                    "reviewer": body["reviewer"],
                    "notes": body.get("notes"),
                },
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


def test_staged_choices_record_full_audit_and_save_only_approved() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "trip_id": SYDNEY,
                "selections": [
                    {
                        "activity_id": ACTIVITY_ID,
                        "date": "2027-04-02",
                        "start_time": "09:30",
                    }
                ],
                "item_decisions": [
                    {
                        "activity_id": ACTIVITY_ID,
                        "decision": "approve",
                        "trip_id": SYDNEY,
                        "date": "2027-04-02",
                        "start_time": "09:30",
                    },
                    {
                        "activity_id": OTHER,
                        "decision": "reject",
                        "notes": "Too expensive",
                    },
                ],
            },
        )
        refreshed = client.get(PATH)
    assert len(refreshed.json()["item_decisions"]) == 2
    assert refreshed.json()["answer"]["parts"] == workflow.run["result"]["parts"]
    assert response.status_code == 200, response.text
    assert response.json()["saved"][0]["activity_id"] == ACTIVITY_ID
    audit = json.loads(workflow.posts[0]["notes"])
    assert audit["activity_reviews"][1][2] == "Too expensive"
    assert workflow.posts[0]["decision"] == "correct"
    assert len(response.json()["item_decisions"]) == 2
    assert response.json()["answer"]["parts"] == workflow.run["result"]["parts"]
    assert list(itinerary.rows) == [(SYDNEY, ACTIVITY_ID)]


def test_all_rejected_choices_record_reasons_without_itinerary_write() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "reject",
                "reviewer": "Julian",
                "item_decisions": [
                    {"activity_id": ACTIVITY_ID, "decision": "reject"},
                    {
                        "activity_id": OTHER,
                        "decision": "reject",
                        "notes": "Too crowded",
                    },
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "rejected"
    assert (
        json.loads(workflow.posts[0]["notes"])["activity_reviews"][1][2]
        == "Too crowded"
    )
    assert itinerary.rows == {}


def test_incomplete_duplicate_or_mismatched_choices_are_not_submitted() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    choices = [
        [{"activity_id": ACTIVITY_ID, "decision": "reject"}],
        [{"activity_id": ACTIVITY_ID, "decision": "reject"}] * 2,
        [
            {
                "activity_id": ACTIVITY_ID,
                "decision": "approve",
                "trip_id": SYDNEY,
                "date": "2027-04-02",
                "start_time": "09:30",
            },
            {"activity_id": OTHER, "decision": "reject"},
        ],
        [
            {"activity_id": ACTIVITY_ID, "decision": "reject", "notes": "x" * 1000},
            {"activity_id": OTHER, "decision": "reject"},
        ],
    ]
    with app(workflow, itinerary) as client:
        for items in choices:
            response = client.post(
                f"{PATH}/review",
                json={
                    "decision": "reject",
                    "reviewer": "Julian",
                    "item_decisions": items,
                },
            )
            assert response.status_code == 400, response.text
    assert workflow.posts == []
    assert itinerary.rows == {}


def test_staged_review_requires_shared_audit_confirmation_before_additions() -> None:
    for missing in (True, False):
        workflow, itinerary = Workflow(), FakeItinerary()

        def corrupt_notes(
            request: httpx.Request,
            workflow: Workflow = workflow,
            missing: bool = missing,
        ) -> httpx.Response:
            workflow.handle(request)
            if request.method == "POST" and request.url.path.endswith("/review"):
                workflow.run["human"]["notes"] = None if missing else "Another review"
            return httpx.Response(200, json={"data": workflow.run})

        with TestClient(
            create_app(
                Settings(multi_agent_enabled=True),
                multi_agent_transport=httpx.MockTransport(corrupt_notes),
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
                    "trip_id": SYDNEY,
                    "selections": [
                        {
                            "activity_id": ACTIVITY_ID,
                            "date": "2027-04-02",
                            "start_time": "09:30",
                        }
                    ],
                    "item_decisions": [
                        {
                            "activity_id": ACTIVITY_ID,
                            "decision": "approve",
                            "trip_id": SYDNEY,
                            "date": "2027-04-02",
                            "start_time": "09:30",
                        },
                        {
                            "activity_id": OTHER,
                            "decision": "reject",
                            "notes": "Too expensive",
                        },
                    ],
                },
            )
        assert response.status_code == 502, response.text
        assert "audit" in response.json()["detail"]
        assert len(workflow.posts) == 1
        assert itinerary.rows == {}


def test_staged_approval_requires_schedule_and_retains_per_card_trip() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    with app(workflow, itinerary) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        base = {"activity_id": ACTIVITY_ID, "trip_id": SYDNEY}
        body = {
            "decision": "approve",
            "reviewer": "Julian",
            "selections": [base],
            "item_decisions": [
                {**base, "decision": "approve"},
                {"activity_id": OTHER, "decision": "reject"},
            ],
        }
        assert client.post(f"{PATH}/review", json=body).status_code == 400
        assert not workflow.posts and not itinerary.rows
        selected = {**base, "date": "2027-04-02", "start_time": "09:30"}
        body["selections"] = [selected]
        body["item_decisions"] = [
            {**selected, "decision": "approve"},
            {"activity_id": OTHER, "decision": "reject"},
        ]
        response = client.post(f"{PATH}/review", json=body)
        assert response.status_code == 200, response.text
        choice = client.get(PATH).json()["item_decisions"][0]
        assert choice["trip_id"] == SYDNEY and choice["date"] == "2027-04-02"
        assert choice["start_time"] == "09:30"


def test_two_approved_cards_use_their_own_trips_after_one_shared_gate() -> None:
    from copy import deepcopy

    from tests.backend.test_itinerary_api import TOKYO

    workflow, itinerary, database = Workflow(), FakeItinerary(), FakeDatabase()

    def db(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/internal/activity/{OTHER}":
            row = deepcopy(database.records[ACTIVITY_ID])
            row["id"] = OTHER
            return httpx.Response(200, json=row)
        return database.handle(request)

    def trip(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            assert len(workflow.posts) == 1
            trip_id, activity_id = request.url.path.split("/")[-3::2]
            row = {
                "trip_id": trip_id,
                "activity_id": activity_id,
                **json.loads(request.content),
            }
            itinerary.rows[(trip_id, activity_id)] = row
            return httpx.Response(200, json={"data": row})
        return itinerary.handle(request)

    selections = [
        {
            "activity_id": ACTIVITY_ID,
            "trip_id": SYDNEY,
            "date": "2027-04-02",
            "start_time": "09:30",
        },
        {
            "activity_id": OTHER,
            "trip_id": TOKYO,
            "date": "2027-05-11",
            "start_time": "10:15",
        },
    ]
    with TestClient(
        create_app(
            Settings(multi_agent_enabled=True),
            multi_agent_transport=httpx.MockTransport(workflow.handle),
            itinerary_transport=httpx.MockTransport(trip),
            database_transport=httpx.MockTransport(db),
            location_transport=httpx.MockTransport(location_handler),
        )
    ) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        payload = {
            "decision": "approve",
            "reviewer": "Julian",
            "selections": selections,
            "item_decisions": [{**row, "decision": "approve"} for row in selections],
        }
        invalid = json.loads(json.dumps(payload))
        invalid["selections"][1]["date"] = "2028-01-01"
        invalid["item_decisions"][1]["date"] = "2028-01-01"
        assert client.post(f"{PATH}/review", json=invalid).status_code == 400
        assert not workflow.posts and not itinerary.rows
        response = client.post(f"{PATH}/review", json=payload)
        assert response.status_code == 200, response.text
        assert len(response.json()["saved"]) == 2
        assert itinerary.rows[(SYDNEY, ACTIVITY_ID)]["start_time"] == "09:30"
        assert itinerary.rows[(TOKYO, OTHER)]["start_time"] == "10:15"
        assert client.post(f"{PATH}/review", json=payload).status_code == 409
        assert len(workflow.posts) == 1
        refreshed = client.get(PATH).json()["item_decisions"]
        assert [row["trip_id"] for row in refreshed] == [SYDNEY, TOKYO]


def test_staged_approval_applies_chosen_schedule_to_existing_membership() -> None:
    workflow, itinerary = Workflow(), FakeItinerary()
    itinerary.rows[(SYDNEY, ACTIVITY_ID)] = {
        "activity_id": ACTIVITY_ID,
        "trip_id": SYDNEY,
        "date": "2027-04-01",
        "start_time": "08:00",
    }
    choice = {
        "activity_id": ACTIVITY_ID,
        "trip_id": SYDNEY,
        "date": "2027-04-02",
        "start_time": "10:30",
    }
    with app(workflow, itinerary) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            f"{PATH}/review",
            json={
                "decision": "approve",
                "reviewer": "Julian",
                "selections": [choice],
                "item_decisions": [
                    {**choice, "decision": "approve"},
                    {"activity_id": OTHER, "decision": "reject"},
                ],
            },
        )
    assert response.status_code == 200, response.text
    assert itinerary.rows[(SYDNEY, ACTIVITY_ID)]["date"] == "2027-04-02"
    assert response.json()["saved"][0]["status"] == "updated"
