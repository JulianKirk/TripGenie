"""Release 2: transport planning through the shared Multi-Agent Server.

The server is replaced by a stateful fake behind an injected transport. These
tests pin this service's side of the contract -- the run request it sends, how
it reads a run back, how a human decision is forwarded, and that only grounded
suggestions a human approved are added to a trip -- without a live server.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

from tests.backend.conftest import FakeItineraryApi

TRIPS_BASE_URL = "http://student-1-backend:8001"
RUN_ID = "magent_0123456789ab"
FERRY = "transport_2026_spirit_geelong_devonport"
FLIGHT = "transport_2026_qf401_mel_syd"
SOLD_OUT = "transport_2026_sq232_syd_sin"
INVENTED = "transport_2026_made_up_route"
TRIP = "trip_2027_queenstown_ski_escape"
QUESTION = "Best way to Tasmania from Geelong for four?"


def search_trace(*ids: str, status: str = "success") -> dict[str, Any]:
    return {
        "tool": "transport_search",
        "arguments": {"origin": "Geelong", "limit": 12},
        "status": status,
        "duration_ms": 18,
        "result": {
            "content": [],
            "structuredContent": {
                "ok": status == "success",
                "source": "student-3",
                "data": {"items": [{"id": value} for value in ids]},
            },
            "isError": status != "success",
        },
        "error": None if status == "success" else "INVALID_ARGUMENTS",
    }


def awaiting_run(
    suggestions: list[dict[str, str]],
    tools: list[dict[str, Any]],
    *,
    trip_id: str | None = TRIP,
) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "feature": "student-3",
        "task": QUESTION,
        "trip_id": trip_id,
        "correlation_id": "student3-agents-abc",
        "status": "awaiting_human",
        "created_at": "2026-10-22T01:00:00Z",
        "updated_at": "2026-10-22T01:02:00Z",
        "attempts": 1,
        "plan": {
            "goal": "Find transport from Geelong to Tasmania for four.",
            "steps": ['transport_search {"origin": "Geelong"}'],
            "required_evidence": ["prices from transport_search"],
            "tools_to_use": ["transport_search"],
            "success_criteria": ["every id comes from a tool result"],
        },
        "steps": [
            {
                "agent": "planner",
                "attempt": 1,
                "status": "completed",
                "duration_ms": 30000,
                "output": {},
                "tools": [],
            },
            {
                "agent": "worker",
                "attempt": 1,
                "status": "completed",
                "duration_ms": 20000,
                "output": {},
                "tools": tools,
            },
            {
                "agent": "reviewer",
                "attempt": 1,
                "status": "completed",
                "duration_ms": 4000,
                "output": {},
                "tools": [],
            },
        ],
        "checks": [
            {
                "name": "grounding",
                "passed": True,
                "blocking": True,
                "detail": "all ids came from tool results",
            },
        ],
        "review": {
            "verdict": "approve",
            "summary": "Supported by transport_search.",
            "issues": [],
            "risks": ["Availability may change."],
            "recommendations": [],
        },
        "result": {
            "overview": "The Spirit of Tasmania ferry is the only crossing.",
            "suggestions": suggestions,
            "considerations": ["Book a cabin early."],
            "disclaimer": "Advisory only; review before adding to your trip.",
        },
        "proposed_actions": suggestions,
        "human": None,
        "final_result": None,
        "approved_actions": [],
        "error": None,
    }


class FakeMultiAgent:
    """The shared server as this service sees it: one stored run."""

    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.reviews: list[dict[str, Any]] = []
        self.run = awaiting_run(
            [
                {"transport_id": FERRY, "reason": "Overnight ferry, $289.00."},
                {"transport_id": INVENTED, "reason": "A route no tool returned."},
            ],
            [search_trace(FERRY, FLIGHT)],
        )
        self.reply: httpx.Response | None = None
        self.review_reply: httpx.Response | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.reply is not None:
            return self.reply
        path = request.url.path
        if request.method == "POST" and path == "/runs":
            body = json.loads(request.content)
            self.started.append(body)
            return httpx.Response(
                202,
                json={
                    "data": {
                        **self.run,
                        "task": body["task"],
                        "trip_id": body["trip_id"],
                        "status": "planning",
                        "attempts": 0,
                        "plan": None,
                        "steps": [],
                        "checks": [],
                        "review": None,
                        "result": None,
                        "proposed_actions": [],
                    },
                },
            )
        if path == f"/runs/{RUN_ID}" and request.method == "GET":
            return httpx.Response(200, json={"data": self.run})
        if path == f"/runs/{RUN_ID}/review" and request.method == "POST":
            if self.review_reply is not None:
                return self.review_reply
            body = json.loads(request.content)
            self.reviews.append(body)
            return httpx.Response(200, json={"data": self._decide(body)})
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "RUN_NOT_FOUND",
                    "message": "Run was not found.",
                    "details": [],
                },
            },
        )

    def _decide(self, body: dict[str, Any]) -> dict[str, Any]:
        """The server's own decision rules, as far as these tests need them."""
        proposed = self.run["proposed_actions"]
        final = self.run["result"]
        approved: list[dict[str, Any]] = []
        if body["decision"] == "approve":
            approved = list(proposed)
        elif body["decision"] == "partial":
            approved = [proposed[index] for index in body["accepted_actions"]]
        elif body["decision"] == "correct":
            final = body["corrected_result"]
            approved = list(final["suggestions"])
        else:
            final = None
        return {
            **self.run,
            "status": "rejected" if body["decision"] == "reject" else "completed",
            "human": {
                "decision": body["decision"],
                "reviewer": body["reviewer"],
                "notes": body.get("notes"),
                "decided_at": "2026-10-22T01:03:00Z",
                "accepted_actions": [],
            },
            "final_result": final,
            "approved_actions": approved,
        }


@pytest.fixture
def fake_server() -> FakeMultiAgent:
    return FakeMultiAgent()


@pytest.fixture
def agents_client(
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
    fake_server: FakeMultiAgent,
) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            database_api_base_url="http://student-3-database:8004",
            trips_api_base_url=TRIPS_BASE_URL,
            multi_agent_enabled=True,
        ),
        transport=database_transport,
        trips_transport=itinerary_transport,
        multi_agent_transport=httpx.MockTransport(fake_server.handle),
    )
    with TestClient(app) as test_client:
        yield test_client


def _review(client: TestClient, **body: object) -> httpx.Response:
    return client.post(f"/api/transport-options/agent-runs/{RUN_ID}/review", json=body)


# -------------------------------------------------------------- starting


def test_a_run_is_started_with_this_features_prompt_tools_and_grounding(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    response = agents_client.post(
        "/api/transport-options/agent-runs",
        json={"question": f"  {QUESTION} ", "origin": "Geelong", "trip_id": TRIP},
    )

    assert response.status_code == 202, response.text
    run = response.json()["data"]
    assert run["run_id"] == RUN_ID
    assert run["status"] == "planning"
    assert run["task"] == QUESTION
    assert run["suggestions"] == []

    (body,) = fake_server.started
    assert body["feature"] == "student-3"
    assert body["task"] == QUESTION
    assert body["trip_id"] == TRIP
    # The Worker gets the same prompt and first search as AI suggestions.
    assert "Call `transport_search` first" in body["worker_system"]
    assert body["context"] == {
        "question": QUESTION,
        "first_search": {"limit": 12, "origin": "Geelong"},
    }
    assert body["output_schema"]["title"] == "TransportRecommendationDraft"
    assert "allowed_tools" not in body
    assert body["grounding"] == {
        "source": "student-3",
        "id_paths": ["suggestions[].transport_id"],
    }
    assert body["actions_path"] == "suggestions"
    assert body["correlation_id"].startswith("student3-agents-")


def test_a_route_with_nothing_bookable_is_refused_before_any_run(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    response = agents_client.post(
        "/api/transport-options/agent-runs",
        json={"question": "Any way?", "origin": "Atlantis"},
    )

    assert response.status_code == 422
    assert fake_server.started == []


def test_the_question_is_required(agents_client: TestClient) -> None:
    response = agents_client.post("/api/transport-options/agent-runs", json={})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "question"


# --------------------------------------------------------------- reading


def test_a_run_is_read_back_with_only_grounded_suggestions_resolved(
    agents_client: TestClient,
) -> None:
    response = agents_client.get(f"/api/transport-options/agent-runs/{RUN_ID}")

    assert response.status_code == 200, response.text
    run = response.json()["data"]
    assert run["status"] == "awaiting_human"
    assert run["plan"]["goal"].startswith("Find transport")
    assert [(s["agent"], s["attempt"]) for s in run["stages"]] == [
        ("planner", 1),
        ("worker", 1),
        ("reviewer", 1),
    ]
    worker = run["stages"][1]
    assert worker["tools"][0]["tool"] == "transport_search"
    assert worker["tools"][0]["transport_ids"] == [FERRY, FLIGHT]
    assert run["checks"] == [
        {
            "name": "grounding",
            "passed": True,
            "detail": "all ids came from tool results",
        },
    ]
    assert run["review"]["verdict"] == "approve"
    assert run["review"]["risks"] == ["Availability may change."]
    assert run["overview"].startswith("The Spirit of Tasmania")
    ferry, invented = run["suggestions"]
    assert ferry["grounded"] is True
    # Re-read from this service, not the model's copy.
    assert ferry["option"]["id"] == FERRY
    assert ferry["option"]["provider"]
    assert invented["grounded"] is False
    assert invented["option"] is None


def test_a_failed_run_shows_its_error_and_the_failed_stage(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    fake_server.run["status"] = "failed"
    fake_server.run["error"] = {"code": "BAD_GATEWAY", "message": "Tool calls failed."}
    fake_server.run["steps"][1] |= {
        "status": "failed",
        "error": {"code": "BAD_GATEWAY", "message": "Tool calls failed."},
        "tools": [search_trace(status="rejected")],
    }
    fake_server.run["result"] = None

    run = agents_client.get(f"/api/transport-options/agent-runs/{RUN_ID}").json()[
        "data"
    ]

    assert run["status"] == "failed"
    assert run["error"] == {"code": "BAD_GATEWAY", "message": "Tool calls failed."}
    worker = run["stages"][1]
    assert worker["status"] == "failed"
    assert worker["error_code"] == "BAD_GATEWAY"
    assert worker["tools"][0]["status"] == "rejected"
    assert run["suggestions"] == []


def test_an_unknown_run_is_not_found(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    response = agents_client.get(
        "/api/transport-options/agent-runs/magent_ffffffffffff",
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_a_malformed_run_id_is_refused_without_calling_the_server(
    agents_client: TestClient,
) -> None:
    response = agents_client.get("/api/transport-options/agent-runs/not-a-run")

    assert response.status_code == 422


# -------------------------------------------------------- human decision


def test_approving_adds_grounded_suggestions_to_the_trip(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    response = _review(
        agents_client,
        decision="approve",
        reviewer="ronit",
        notes="Looks right",
        traveller_count=4,
    )

    assert response.status_code == 200, response.text
    run = response.json()["data"]
    assert fake_server.reviews == [
        {"decision": "approve", "reviewer": "ronit", "notes": "Looks right"},
    ]
    assert run["status"] == "completed"
    assert run["human"]["decision"] == "approve"
    assert run["saved"] == [
        {"transport_id": FERRY, "trip_id": TRIP, "traveller_count": 4},
    ]
    # The invented id is never added, even though the human approved it.
    assert run["save_errors"] == [
        {
            "transport_id": INVENTED,
            "code": "UNGROUNDED_SUGGESTION",
            "message": "No transport tool returned this id, so it was not added.",
        },
    ]
    pin = itinerary_api.pins[(TRIP, FERRY)]
    assert pin["traveller_count"] == 4
    assert RUN_ID in str(pin["notes"])
    assert (TRIP, INVENTED) not in itinerary_api.pins


def test_partial_acceptance_adds_only_the_chosen_suggestions(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    fake_server.run = awaiting_run(
        [
            {"transport_id": FERRY, "reason": "Ferry."},
            {"transport_id": FLIGHT, "reason": "Flight."},
        ],
        [search_trace(FERRY, FLIGHT)],
    )

    run = _review(
        agents_client,
        decision="partial",
        accepted=[1],
        traveller_count=2,
    ).json()["data"]

    assert fake_server.reviews[0]["accepted_actions"] == [1]
    assert [item["transport_id"] for item in run["saved"]] == [FLIGHT]
    assert set(itinerary_api.pins) == {(TRIP, FLIGHT)}


def test_a_correction_sends_the_corrected_answer_and_adds_its_suggestions(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    run = _review(
        agents_client,
        decision="correct",
        corrected_overview="Take the ferry; there is no flight from Geelong.",
        accepted=[0],
        traveller_count=4,
    ).json()["data"]

    corrected = fake_server.reviews[0]["corrected_result"]
    assert corrected["overview"] == "Take the ferry; there is no flight from Geelong."
    assert corrected["suggestions"] == [
        {"transport_id": FERRY, "reason": "Overnight ferry, $289.00."},
    ]
    assert corrected["disclaimer"].startswith("Advisory only")
    # The view shows the answer the human signed off.
    assert run["overview"] == "Take the ferry; there is no flight from Geelong."
    assert [item["transport_id"] for item in run["suggestions"]] == [FERRY]
    assert [item["transport_id"] for item in run["saved"]] == [FERRY]


def test_rejecting_saves_nothing(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    run = _review(agents_client, decision="reject", notes="Wrong route").json()["data"]

    assert fake_server.reviews == [
        {"decision": "reject", "reviewer": "traveller", "notes": "Wrong route"},
    ]
    assert run["status"] == "rejected"
    assert run["saved"] == []
    assert itinerary_api.pins == {}


def test_without_a_trip_approval_saves_nothing(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    fake_server.run = awaiting_run(
        [{"transport_id": FERRY, "reason": "Ferry."}],
        [search_trace(FERRY)],
        trip_id=None,
    )

    run = _review(agents_client, decision="approve").json()["data"]

    assert run["status"] == "completed"
    assert run["saved"] == []
    assert itinerary_api.pins == {}


def test_an_unplannable_option_is_reported_not_added(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    fake_server.run = awaiting_run(
        [
            {"transport_id": SOLD_OUT, "reason": "Sold out."},
            {"transport_id": FERRY, "reason": "Ferry."},
        ],
        [search_trace(SOLD_OUT, FERRY)],
    )

    run = _review(agents_client, decision="approve", traveller_count=1).json()["data"]

    assert [item["transport_id"] for item in run["saved"]] == [FERRY]
    (error,) = run["save_errors"]
    assert error["transport_id"] == SOLD_OUT
    assert error["code"] != "UNGROUNDED_SUGGESTION"
    assert set(itinerary_api.pins) == {(TRIP, FERRY)}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"decision": "partial", "traveller_count": 1}, "accepted"),
        ({"decision": "partial", "accepted": [5], "traveller_count": 1}, "accepted"),
        ({"decision": "correct", "traveller_count": 1}, "corrected_overview"),
        ({"decision": "approve"}, "traveller_count"),
    ],
)
def test_an_incomplete_decision_is_refused_before_it_reaches_the_server(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    body: dict[str, object],
    field: str,
) -> None:
    response = _review(agents_client, **body)

    assert response.status_code == 422
    assert field in {d["field"] for d in response.json()["error"]["details"]}
    assert fake_server.reviews == []


def test_a_second_decision_is_refused_by_the_server_and_saves_nothing(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary_api: FakeItineraryApi,
) -> None:
    fake_server.run["status"] = "completed"
    fake_server.review_reply = httpx.Response(
        409,
        json={
            "error": {
                "code": "RUN_NOT_AWAITING_REVIEW",
                "message": "Run is completed, not awaiting a human decision.",
                "details": [{"field": "status", "issue": "completed"}],
            },
        },
    )
    response = _review(agents_client, decision="approve", traveller_count=4)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_AWAITING_REVIEW"
    assert itinerary_api.pins == {}


# --------------------------------------------------------------- failures


def test_everything_is_refused_while_disabled(client: TestClient) -> None:
    responses = [
        client.post("/api/transport-options/agent-runs", json={"question": "x"}),
        client.get(f"/api/transport-options/agent-runs/{RUN_ID}"),
        _review(client, decision="reject"),
    ]

    for response in responses:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MULTI_AGENT_DISABLED"
    assert client.get("/health").json()["data"]["integrations"]["multi_agent"] == (
        "disabled"
    )


def test_health_reports_multi_agent_enabled_without_contacting_it(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    response = agents_client.get("/ready")

    assert response.status_code == 200
    assert response.json()["data"]["integrations"]["multi_agent"] == "enabled"
    assert fake_server.started == []


def test_an_unreachable_server_is_reported_as_unavailable(
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    app = create_app(
        Settings(
            database_api_base_url="http://student-3-database:8004",
            trips_api_base_url=TRIPS_BASE_URL,
            multi_agent_enabled=True,
        ),
        transport=database_transport,
        trips_transport=itinerary_transport,
        multi_agent_transport=httpx.MockTransport(refuse),
    )
    with TestClient(app) as client:
        response = client.get(f"/api/transport-options/agent-runs/{RUN_ID}")
        browse = client.get("/api/transport-options")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert browse.status_code == 200


@pytest.mark.parametrize(
    ("reply", "status_code", "code"),
    [
        (
            httpx.Response(
                503,
                json={
                    "error": {
                        "code": "RUN_LIMIT_REACHED",
                        "message": "Busy.",
                        "details": [],
                    },
                },
            ),
            503,
            "RUN_LIMIT_REACHED",
        ),
        (httpx.Response(500, text="boom"), 502, "BAD_GATEWAY"),
        (httpx.Response(200, json={"data": {"run_id": RUN_ID}}), 502, "BAD_GATEWAY"),
    ],
)
def test_server_errors_are_translated(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    reply: httpx.Response,
    status_code: int,
    code: str,
) -> None:
    fake_server.reply = reply

    response = agents_client.get(f"/api/transport-options/agent-runs/{RUN_ID}")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
