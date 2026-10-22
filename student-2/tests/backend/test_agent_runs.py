"""Release 2 multi-agent planning -- this service calling the shared server.

The Multi-Agent Server is a `MockTransport` here: the interesting cases are the
run request this service builds, the grounding guard, and what a human decision
may and may not write to a trip. The agents themselves are covered by the
server's own tests.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import (
    DEFAULT_MULTI_AGENT_TIMEOUT,
    DEFAULT_MULTI_AGENT_URL,
    Settings,
)

DATABASE_URL = "http://database.test"
LOCATION_URL = "http://location.test"
ITINERARY_URL = "http://itinerary.test"
AGENTS_URL = "http://agents.test"

GROUNDED = "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
OTHER = "7a1d2c33-1b2c-4d5e-8f60-123456789abc"
INVENTED = "00000000-0000-4000-8000-000000000000"
RUN_ID = "magent_0123456789ab"
TRIP = "trip_sydney"
BASE = "/accommodation/agent-runs"

LISTING = {
    "id": GROUNDED,
    "name": "Harbour Hotel",
    "type": "hotel",
    "price_per_night": 120.0,
    "availability_status": "available",
    "rating": 4.5,
    "location_details": {},
}


def listing(accommodation_id: str, name: str) -> dict:
    return {**LISTING, "id": accommodation_id, "name": name}


def tool_trace(*ids: str, tool: str = "accommodations_search", **extra) -> dict:
    """One successful MCP call, shaped the way AI-Mode reports it."""
    data = {"items": [{"id": value} for value in ids]}
    return {
        "tool": tool,
        "arguments": {"country": "Australia"},
        "status": "success",
        "duration_ms": 12,
        "result": {
            "structuredContent": {"ok": True, "source": "student-2", "data": data}
        },
        **extra,
    }


def run_record(
    *,
    state: str = "awaiting_human",
    suggestions=(GROUNDED,),
    tools=None,
    trip_id: str | None = TRIP,
    **extra,
) -> dict:
    result = {
        "overview": "Harbour Hotel fits the budget.",
        "suggestions": [
            {"accommodation_id": value, "reason": f"Reason for {value[:4]}"}
            for value in suggestions
        ],
        "considerations": ["Prices are per night."],
    }
    return {
        "run_id": RUN_ID,
        "feature": "student-2",
        "status": state,
        "task": "A cheap stay in Sydney",
        "trip_id": trip_id,
        "attempts": 1,
        "created_at": "2027-01-01T00:00:00Z",
        "updated_at": "2027-01-01T00:00:05Z",
        "plan": {"goal": "Find a stay", "steps": ["search", "answer"]},
        "steps": [
            {"agent": "planner", "attempt": 1, "status": "completed", "duration_ms": 5},
            {
                "agent": "worker",
                "attempt": 1,
                "status": "completed",
                "duration_ms": 50,
                "tools": [tool_trace(GROUNDED)] if tools is None else tools,
            },
        ],
        "checks": [{"name": "grounding", "passed": True, "detail": "ok"}],
        "review": {"verdict": "approve", "summary": "Looks right."},
        "result": result,
        **extra,
    }


class FakeServer:
    """The Multi-Agent Server: one run, its requests recorded."""

    def __init__(self, run: dict | None = None):
        self.run = run or run_record()
        self.requests: list[tuple[str, str, dict | None]] = []
        self.failure: httpx.Response | Exception | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if isinstance(self.failure, Exception):
            raise self.failure
        if self.failure is not None:
            return self.failure
        if request.url.path.endswith("/review"):
            decision = body["decision"]
            self.run = deepcopy(self.run)
            self.run["human"] = {
                "decision": decision,
                "reviewer": body["reviewer"],
                "notes": body.get("notes"),
                "decided_at": "2027-01-01T00:01:00Z",
            }
            suggestions = self.run["result"]["suggestions"]
            if decision == "approve":
                self.run["approved_actions"] = suggestions
            elif decision == "partial":
                self.run["approved_actions"] = [
                    suggestions[index] for index in body["accepted_actions"]
                ]
            elif decision == "correct":
                self.run["final_result"] = body["corrected_result"]
                self.run["approved_actions"] = body["corrected_result"]["suggestions"]
            else:
                self.run["approved_actions"] = []
            self.run["status"] = "rejected" if decision == "reject" else "completed"
        return httpx.Response(200, json={"data": self.run})


class FakeDatabase:
    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        record_id = request.url.path.rsplit("/", 1)[-1]
        names = {GROUNDED: "Harbour Hotel", OTHER: "Other Inn"}
        if record_id not in names:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=listing(record_id, names[record_id]))


class FakeItinerary:
    def __init__(self):
        self.pinned: list[tuple[str, str, dict]] = []
        self.refuse: httpx.Response | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/trips":
            return httpx.Response(200, json={"data": [{"id": TRIP, "name": "Sydney"}]})
        if request.method == "PUT":
            if self.refuse is not None:
                return self.refuse
            parts = path.split("/")
            body = json.loads(request.content)
            self.pinned.append((parts[-1], parts[-3], body))
            return httpx.Response(200, json={"data": {"trip_id": parts[-3]}})
        return httpx.Response(404, json={"error": {"message": "nope"}})


def places(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if "country" in str(request.url):
        return httpx.Response(
            200,
            json={
                "countries": [
                    {"id": "9a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b", "name": "australia"}
                ],
                "total": 1,
            },
        )
    return httpx.Response(
        200,
        json={
            "cities": [
                {
                    "id": "1a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b",
                    "country_id": "9a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b",
                    "name": "sydney",
                }
            ],
            "total": 1,
        },
    )


@pytest.fixture
def agents():
    @contextmanager
    def factory(server: FakeServer | None = None, *, enabled: bool = True):
        server = server or FakeServer()
        itinerary = FakeItinerary()
        app = create_app(
            Settings(
                database_url=DATABASE_URL,
                location_url=LOCATION_URL,
                itinerary_url=ITINERARY_URL,
                multi_agent_enabled=enabled,
                multi_agent_base_url=AGENTS_URL,
            ),
            transport=httpx.MockTransport(FakeDatabase().handle),
            location_transport=httpx.MockTransport(places),
            itinerary_transport=httpx.MockTransport(itinerary.handle),
            multi_agent_transport=httpx.MockTransport(server.handle),
        )
        with TestClient(app) as client:
            yield client, server, itinerary

    return factory


class TestSettings:
    def test_off_by_default_and_pointing_at_the_host_server(self):
        settings = Settings()
        assert settings.multi_agent_enabled is False
        assert settings.multi_agent_base_url == DEFAULT_MULTI_AGENT_URL
        assert settings.multi_agent_timeout == DEFAULT_MULTI_AGENT_TIMEOUT

    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")
        monkeypatch.setenv("MULTI_AGENT_BASE_URL", AGENTS_URL)
        monkeypatch.setenv("MULTI_AGENT_TIMEOUT", "2.5")
        settings = Settings.from_env()
        assert settings.multi_agent_enabled is True
        assert settings.multi_agent_base_url == AGENTS_URL
        assert settings.multi_agent_timeout == 2.5

    @pytest.mark.parametrize("value", ["false", "", "0", "no"])
    def test_anything_else_is_off(self, monkeypatch, value):
        monkeypatch.setenv("MULTI_AGENT_ENABLED", value)
        assert Settings.from_env().multi_agent_enabled is False


class TestDisabled:
    def test_every_route_says_so_and_never_calls_the_server(self, agents):
        with agents(enabled=False) as (client, server, _):
            started = client.post(BASE, json={"question": "a cheap stay"})
            polled = client.get(f"{BASE}/{RUN_ID}")
            decided = client.post(
                f"{BASE}/{RUN_ID}/review", json={"decision": "reject"}
            )
            health = client.get("/health").json()
        for response in (started, polled, decided):
            assert response.status_code == 503
            assert "MULTI_AGENT_DISABLED" in response.json()["detail"]
        assert server.requests == []
        assert health["multi_agent"] == "disabled"

    def test_health_reports_enabled(self, agents):
        with agents() as (client, _, _):
            assert client.get("/health").json()["multi_agent"] == "enabled"


class TestStartingARun:
    def test_the_run_request_carries_this_features_prompt_schema_and_grounding(
        self, agents
    ):
        server = FakeServer(run_record(state="planning", tools=[]))
        with agents(server) as (client, server, _):
            response = client.post(
                BASE,
                json={
                    "question": "A cheap stay in Sydney",
                    "trip_id": TRIP,
                    "country": "Australia",
                    "city": "Sydney",
                },
            )
        assert response.status_code == 202
        assert response.json()["status"] == "planning"
        method, path, body = server.requests[0]
        assert (method, path) == ("POST", "/runs")
        assert body["feature"] == "student-2"
        assert body["task"] == "A cheap stay in Sydney"
        assert body["trip_id"] == TRIP
        assert body["grounding"] == {
            "source": "student-2",
            "id_paths": ["suggestions[].accommodation_id"],
        }
        assert body["actions_path"] == "suggestions"
        assert set(body["allowed_tools"]) == {
            "accommodations_search",
            "accommodations_get",
            "accommodations_committed_costs",
        }
        assert body["context"]["country"] == "Australia"
        assert body["context"]["known_countries"] == ["australia"]
        assert body["output_schema"]["properties"]["suggestions"]
        assert "accommodations_search" in body["worker_system"]
        assert body["correlation_id"].startswith("student2-agents-")

    def test_an_unknown_trip_is_refused_before_the_server_is_called(self, agents):
        with agents() as (client, server, _):
            response = client.post(BASE, json={"question": "x", "trip_id": "trip_nope"})
        assert response.status_code == 404
        assert server.requests == []

    def test_a_blank_question_is_a_validation_error(self, agents):
        with agents() as (client, server, _):
            response = client.post(BASE, json={"question": ""})
        assert response.status_code == 400
        assert server.requests == []


class TestReadingARun:
    def test_a_grounded_suggestion_is_re_read_from_the_database(self, agents):
        with agents() as (client, _, _):
            run = client.get(f"{BASE}/{RUN_ID}").json()
        suggestion = run["suggestions"][0]
        assert suggestion["grounded"] is True
        assert suggestion["accommodation"]["name"] == "Harbour Hotel"
        assert run["stages"][1]["tools"][0]["accommodation_ids"] == [GROUNDED]
        assert run["checks"][0]["passed"] is True

    def test_an_id_no_tool_returned_is_not_grounded_and_not_looked_up(self, agents):
        server = FakeServer(run_record(suggestions=(GROUNDED, INVENTED)))
        with agents(server) as (client, _, _):
            suggestions = client.get(f"{BASE}/{RUN_ID}").json()["suggestions"]
        assert [item["grounded"] for item in suggestions] == [True, False]
        assert "accommodation" not in suggestions[1]

    def test_only_the_final_worker_attempt_grounds_an_id(self, agents):
        run = run_record(suggestions=(OTHER,))
        run["steps"].insert(
            1,
            {
                "agent": "worker",
                "attempt": 1,
                "status": "failed",
                "duration_ms": 5,
                "tools": [tool_trace(OTHER)],
            },
        )
        run["steps"][-1]["attempt"] = 2
        with agents(FakeServer(run)) as (client, _, _):
            suggestion = client.get(f"{BASE}/{RUN_ID}").json()["suggestions"][0]
        assert suggestion["grounded"] is False

    def test_a_failed_tool_call_grounds_nothing(self, agents):
        failed = tool_trace(GROUNDED)
        failed["status"] = "error"
        with agents(FakeServer(run_record(tools=[failed]))) as (client, _, _):
            suggestion = client.get(f"{BASE}/{RUN_ID}").json()["suggestions"][0]
        assert suggestion["grounded"] is False

    def test_a_single_listing_get_grounds_its_id(self, agents):
        get = tool_trace(tool="accommodations_get")
        get["result"]["structuredContent"]["data"] = {"id": GROUNDED}
        with agents(FakeServer(run_record(tools=[get]))) as (client, _, _):
            suggestion = client.get(f"{BASE}/{RUN_ID}").json()["suggestions"][0]
        assert suggestion["grounded"] is True

    def test_a_run_id_that_is_not_one_never_reaches_the_server(self, agents):
        with agents() as (client, server, _):
            response = client.get(f"{BASE}/not-a-run")
        assert response.status_code == 404
        assert server.requests == []

    def test_a_run_this_service_cannot_read_is_a_502(self, agents):
        broken = run_record()
        del broken["task"]
        with agents(FakeServer(broken)) as (client, _, _):
            assert client.get(f"{BASE}/{RUN_ID}").status_code == 502


class TestTheServerMisbehaving:
    def test_unreachable_is_a_503(self, agents):
        server = FakeServer()
        server.failure = httpx.ConnectError("down")
        with agents(server) as (client, _, _):
            response = client.get(f"{BASE}/{RUN_ID}")
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"]

    def test_a_timeout_is_a_503_that_says_so(self, agents):
        server = FakeServer()
        server.failure = httpx.ReadTimeout("slow")
        with agents(server) as (client, _, _):
            response = client.get(f"{BASE}/{RUN_ID}")
        assert response.status_code == 503
        assert "timed out" in response.json()["detail"]

    def test_an_actionable_server_error_is_passed_on(self, agents):
        server = FakeServer()
        server.failure = httpx.Response(
            404, json={"error": {"code": "RUN_NOT_FOUND", "message": "no such run"}}
        )
        with agents(server) as (client, _, _):
            response = client.get(f"{BASE}/{RUN_ID}")
        assert response.status_code == 404
        assert response.json()["detail"] == "RUN_NOT_FOUND: no such run"

    def test_any_other_server_error_is_a_502(self, agents):
        server = FakeServer()
        server.failure = httpx.Response(500, json={"error": {"code": "BOOM"}})
        with agents(server) as (client, _, _):
            assert client.get(f"{BASE}/{RUN_ID}").status_code == 502

    def test_a_body_that_is_not_the_run_contract_is_a_502(self, agents):
        server = FakeServer()
        server.failure = httpx.Response(200, json={"nope": 1})
        with agents(server) as (client, _, _):
            assert client.get(f"{BASE}/{RUN_ID}").status_code == 502


class TestTheHumanDecision:
    def test_approving_pins_only_grounded_suggestions_to_the_trip(self, agents):
        server = FakeServer(run_record(suggestions=(GROUNDED, INVENTED)))
        with agents(server) as (client, server, itinerary):
            response = client.post(
                f"{BASE}/{RUN_ID}/review",
                json={
                    "decision": "approve",
                    "check_in": "2027-04-01",
                    "check_out": "2027-04-03",
                },
            )
        assert response.status_code == 200
        view = response.json()
        assert view["status"] == "completed"
        assert [saved["accommodation_id"] for saved in view["saved"]] == [GROUNDED]
        assert [error["code"] for error in view["save_errors"]] == [
            "UNGROUNDED_SUGGESTION"
        ]
        assert [(a, t) for a, t, _ in itinerary.pinned] == [(GROUNDED, TRIP)]
        assert itinerary.pinned[0][2]["date"] == "2027-04-01"
        assert itinerary.pinned[0][2]["check_out"] == "2027-04-03"
        assert server.requests[-1][2]["decision"] == "approve"

    def test_a_partial_acceptance_sends_and_pins_only_the_chosen_ones(self, agents):
        both = [tool_trace(GROUNDED, OTHER)]
        server = FakeServer(run_record(suggestions=(GROUNDED, OTHER), tools=both))
        with agents(server) as (client, server, itinerary):
            response = client.post(
                f"{BASE}/{RUN_ID}/review",
                json={"decision": "partial", "accepted": [1]},
            )
        assert response.status_code == 200
        assert server.requests[-1][2]["accepted_actions"] == [1]
        assert [a for a, _, _ in itinerary.pinned] == [OTHER]

    def test_rejecting_writes_nothing(self, agents):
        with agents() as (client, _, itinerary):
            response = client.post(
                f"{BASE}/{RUN_ID}/review",
                json={"decision": "reject", "notes": "wrong city"},
            )
        assert response.json()["status"] == "rejected"
        assert itinerary.pinned == []

    def test_a_correction_replaces_the_overview_and_keeps_the_chosen(self, agents):
        both = [tool_trace(GROUNDED, OTHER)]
        server = FakeServer(run_record(suggestions=(GROUNDED, OTHER), tools=both))
        with agents(server) as (client, server, itinerary):
            response = client.post(
                f"{BASE}/{RUN_ID}/review",
                json={
                    "decision": "correct",
                    "accepted": [0],
                    "corrected_overview": "Just the hotel.",
                },
            )
        body = server.requests[-1][2]
        assert body["corrected_result"]["overview"] == "Just the hotel."
        assert len(body["corrected_result"]["suggestions"]) == 1
        assert response.json()["overview"] == "Just the hotel."
        assert [a for a, _, _ in itinerary.pinned] == [GROUNDED]

    @pytest.mark.parametrize(
        "decision",
        [
            {"decision": "partial"},
            {"decision": "partial", "accepted": [5]},
            {"decision": "correct"},
            {
                "decision": "approve",
                "check_in": "2027-04-03",
                "check_out": "2027-04-01",
            },
        ],
    )
    def test_a_decision_that_makes_no_sense_never_reaches_the_server(
        self, agents, decision
    ):
        with agents() as (client, server, itinerary):
            response = client.post(f"{BASE}/{RUN_ID}/review", json=decision)
        assert response.status_code == 400
        assert [method for method, _, _ in server.requests] == ["GET"]
        assert itinerary.pinned == []

    def test_a_run_with_no_trip_records_the_decision_and_pins_nothing(self, agents):
        with agents(FakeServer(run_record(trip_id=None))) as (client, _, itinerary):
            response = client.post(
                f"{BASE}/{RUN_ID}/review", json={"decision": "approve"}
            )
        assert response.status_code == 200
        assert response.json()["saved"] == []
        assert itinerary.pinned == []

    def test_one_refused_pin_does_not_undo_the_decision(self, agents):
        with agents() as (client, _, itinerary):
            itinerary.refuse = httpx.Response(
                422, json={"error": {"code": "X", "message": "stay outside the trip"}}
            )
            response = client.post(
                f"{BASE}/{RUN_ID}/review", json={"decision": "approve"}
            )
        view = response.json()
        assert view["status"] == "completed"
        assert view["saved"] == []
        assert view["save_errors"][0]["message"] == "stay outside the trip"
        assert view["save_errors"][0]["code"] == "HTTP_422"

    def test_a_decision_on_a_settled_run_passes_the_servers_conflict_on(self, agents):
        server = FakeServer()

        def handler(request):
            if request.url.path.endswith("/review"):
                return httpx.Response(
                    409,
                    json={
                        "error": {"code": "RUN_NOT_AWAITING_REVIEW", "message": "done"}
                    },
                )
            return server.handle(request)

        app = create_app(
            Settings(
                multi_agent_enabled=True,
                multi_agent_base_url=AGENTS_URL,
                database_url=DATABASE_URL,
                location_url=LOCATION_URL,
            ),
            transport=httpx.MockTransport(FakeDatabase().handle),
            location_transport=httpx.MockTransport(places),
            multi_agent_transport=httpx.MockTransport(handler),
        )
        with TestClient(app) as client:
            response = client.post(
                f"{BASE}/{RUN_ID}/review", json={"decision": "approve"}
            )
        assert response.status_code == 409
        assert "RUN_NOT_AWAITING_REVIEW" in response.json()["detail"]
