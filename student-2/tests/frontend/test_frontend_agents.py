"""The multi-agent page: start a run, watch it, decide.

The backend is a `MockTransport` that serves one run record and remembers what
the page sent. What matters here is the translation: form fields into the JSON
the backend documents, the run record into a page a person can decide on, and
that nothing about a decision depends on a script.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from frontend_service.app import create_app
from frontend_service.config import Settings

RUN_ID = "magent_0123456789ab"
GROUNDED = "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
OTHER = "7a1d2c33-1b2c-4d5e-8f60-123456789abc"
INVENTED = "00000000-0000-4000-8000-000000000000"
BASE = "/accommodation/agent-runs"
HTMX = {"HX-Request": "true"}


def suggestion(index: int, accommodation_id: str, *, grounded: bool = True) -> dict:
    return {
        "index": index,
        "accommodation_id": accommodation_id,
        "reason": f"Reason {index}",
        "grounded": grounded,
        **(
            {
                "accommodation": {
                    "id": accommodation_id,
                    "name": f"Hotel {index}",
                    "type": "hotel",
                    "price_per_night": 120.0,
                    "rating": 4.5,
                }
            }
            if grounded
            else {}
        ),
    }


def run_view(state: str = "awaiting_human", **extra) -> dict:
    return {
        "run_id": RUN_ID,
        "status": state,
        "task": "A cheap stay in Sydney",
        "trip_id": "trip_sydney",
        "attempts": 1,
        "created_at": "2027-01-01T00:00:00Z",
        "updated_at": "2027-01-01T00:00:05Z",
        "plan": {"goal": "Find a stay", "steps": ["search", "answer"]},
        "stages": [
            {
                "agent": "worker",
                "attempt": 1,
                "status": "completed",
                "duration_ms": 40,
                "tools": [
                    {
                        "tool": "accommodations_search",
                        "status": "success",
                        "accommodation_ids": [GROUNDED, OTHER],
                    }
                ],
            }
        ],
        "checks": [
            {"name": "grounding", "passed": True, "detail": "all ids came from tools"},
            {"name": "schema", "passed": False, "detail": "missing overview"},
        ],
        "review": {"verdict": "approve", "summary": "Looks right."},
        "overview": "Two hotels fit.",
        "considerations": ["Prices are per night."],
        "suggestions": [suggestion(0, GROUNDED), suggestion(1, OTHER)],
        "saved": [],
        "save_errors": [],
        **extra,
    }


class FakeBackend:
    def __init__(self):
        self.run = run_view()
        self.started: list[dict] = []
        self.decisions: list[dict] = []
        self.paths: list[str] = []
        self.timeouts: list[float] = []
        self.start_response: httpx.Response | None = None
        self.read_response: httpx.Response | None = None
        self.review_response: httpx.Response | None = None
        self.trips_response: httpx.Response | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(f"{request.method} {request.url.path}")
        self.timeouts.append(request.extensions["timeout"]["read"])
        body = json.loads(request.content) if request.content else None
        if request.url.path == "/accommodation/trips":
            return self.trips_response or httpx.Response(
                200,
                json={
                    "trips": [
                        {
                            "itinerary_id": "trip_sydney",
                            "name": "Sydney Getaway",
                            "start_date": "2027-04-01",
                            "end_date": "2027-04-05",
                        },
                        {"itinerary_id": "trip_tokyo", "name": "Tokyo City Break"},
                    ]
                },
            )
        if request.method == "POST" and request.url.path == BASE:
            self.started.append(body)
            return self.start_response or httpx.Response(202, json=self.run)
        if request.url.path.endswith("/review"):
            self.decisions.append(body)
            return self.review_response or httpx.Response(200, json=self.run)
        if request.method == "GET" and request.url.path.startswith(BASE):
            return self.read_response or httpx.Response(200, json=self.run)
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def client(backend):
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def post(client, path, **fields):
    return client.post(path, data=fields, headers=HTMX)


class TestStarting:
    def test_the_main_page_links_to_it(self, client):
        assert 'href="/agents"' in client.get("/").text

    def test_the_form_is_offered(self, client):
        html = client.get("/agents").text
        assert 'name="question"' in html
        assert "Start the agents" in html

    def test_the_trip_is_picked_from_a_list_of_names(self, client):
        html = client.get("/agents").text
        assert '<select name="trip_id">' in html
        assert "Sydney Getaway (2027-04-01 to 2027-04-05)" in html
        assert "Tokyo City Break" in html
        assert "No trip" in html

    def test_a_trip_passed_in_the_link_is_preselected(self, client):
        html = client.get("/agents?trip_id=trip_tokyo").text
        assert 'value="trip_tokyo" selected' in html

    def test_the_form_still_works_when_the_trips_cannot_be_loaded(
        self, client, backend
    ):
        backend.trips_response = httpx.Response(503, json={"detail": "down"})
        html = client.get("/agents").text
        assert "No trips could be loaded" in html
        assert 'name="question"' in html

    def test_the_chosen_trip_is_what_starts_the_run(self, client, backend):
        post(client, "/agents", question="cheap stay", trip_id="trip_tokyo")
        assert backend.started == [{"question": "cheap stay", "trip_id": "trip_tokyo"}]

    def test_a_blank_question_is_refused_without_calling_the_backend(
        self, client, backend
    ):
        html = post(client, "/agents", question="  ").text
        assert "Type a question." in html
        assert backend.started == []

    def test_only_what_was_filled_in_is_sent_and_the_run_gets_its_own_page(
        self, client, backend
    ):
        response = post(
            client, "/agents", question="  cheap stay ", trip_id="trip_sydney", city=""
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"/agents/runs/{RUN_ID}"
        assert backend.started == [{"question": "cheap stay", "trip_id": "trip_sydney"}]

    def test_a_backend_error_comes_back_on_the_form_with_what_was_typed(
        self, client, backend
    ):
        backend.start_response = httpx.Response(
            503, json={"detail": "MULTI_AGENT_DISABLED: switched off"}
        )
        html = post(client, "/agents", question="cheap stay").text
        assert "MULTI_AGENT_DISABLED" in html
        assert "cheap stay" in html

    def test_the_agent_calls_wait_longer_than_the_ordinary_five_seconds(
        self, client, backend
    ):
        post(client, "/agents", question="cheap stay")
        client.get(f"/agents/runs/{RUN_ID}")
        post(client, f"/agents/runs/{RUN_ID}/review", decision="reject")
        assert backend.timeouts
        assert all(timeout > 5 for timeout in backend.timeouts)


class TestWatching:
    def test_a_working_run_polls_itself(self, client, backend):
        backend.run = run_view("working", suggestions=[], overview=None, checks=[])
        html = client.get(f"/agents/runs/{RUN_ID}").text
        assert f'hx-get="/agents/runs/{RUN_ID}/panel"' in html
        assert "every 2s" in html
        assert "Worker is searching" in html

    def test_the_panel_alone_is_a_fragment(self, client, backend):
        backend.run = run_view("planning", suggestions=[])
        html = client.get(f"/agents/runs/{RUN_ID}/panel", headers=HTMX).text
        assert "<html" not in html
        assert "every 2s" in html

    def test_a_run_waiting_for_a_person_stops_polling_and_asks(self, client):
        html = client.get(f"/agents/runs/{RUN_ID}").text
        assert "every 2s" not in html
        assert "Approve ticked" in html
        assert "Waiting for your decision" in html

    def test_the_evidence_is_on_the_page(self, client):
        html = client.get(f"/agents/runs/{RUN_ID}").text
        assert "accommodations_search" in html
        assert "returned 2 listing(s)" in html
        assert "Passed:" in html
        assert "Failed:" in html
        assert "Reviewer: approve" in html
        assert "Hotel 0" in html
        assert "$120.00" in html

    def test_an_ungrounded_suggestion_cannot_be_ticked(self, client, backend):
        backend.run = run_view(
            suggestions=[
                suggestion(0, GROUNDED),
                suggestion(1, INVENTED, grounded=False),
            ]
        )
        html = client.get(f"/agents/runs/{RUN_ID}").text
        assert "Not verified" in html
        assert "cannot be added" in html
        assert html.count("disabled") == 1

    def test_a_run_with_no_trip_says_nothing_will_be_added(self, client, backend):
        backend.run = run_view(trip_id=None)
        assert "adds nothing" in client.get(f"/agents/runs/{RUN_ID}").text

    def test_a_settled_run_shows_the_outcome_and_no_form(self, client, backend):
        backend.run = run_view(
            "completed",
            human={
                "decision": "approve",
                "reviewer": "traveller",
                "decided_at": "2027-01-01T00:02:00Z",
            },
            saved=[{"accommodation_id": GROUNDED, "trip_id": "trip_sydney"}],
        )
        html = client.get(f"/agents/runs/{RUN_ID}").text
        assert "Your decision: approve" in html
        assert "Added to trip_sydney" in html
        assert "Approve ticked" not in html

    def test_a_run_id_that_is_not_one_never_reaches_the_backend(self, client, backend):
        html = client.get("/agents/runs/not-a-run").text
        assert "could not be found" in html
        assert backend.paths == []

    def test_a_backend_hiccup_does_not_stop_the_polling(self, client, backend):
        backend.read_response = httpx.Response(503, json={"detail": "unavailable"})
        html = client.get(f"/agents/runs/{RUN_ID}/panel", headers=HTMX).text
        assert "unavailable" in html
        assert "every 2s" in html


class TestDeciding:
    def test_approving_everything_ticked_is_an_approval(self, client, backend):
        post_fields = (
            "decision=approve&offered=0&offered=1&accepted=0&accepted=1"
            "&check_in=2027-04-01"
        )
        client.post(
            f"/agents/runs/{RUN_ID}/review",
            content=post_fields,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert backend.decisions == [
            {"decision": "approve", "accepted": [0, 1], "check_in": "2027-04-01"}
        ]

    def test_approving_only_some_is_a_partial_acceptance(self, client, backend):
        client.post(
            f"/agents/runs/{RUN_ID}/review",
            content="decision=approve&offered=0&offered=1&accepted=1",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert backend.decisions == [{"decision": "partial", "accepted": [1]}]

    def test_approving_with_nothing_ticked_asks_instead_of_sending(
        self, client, backend
    ):
        response = client.post(
            f"/agents/runs/{RUN_ID}/review",
            content="decision=approve&offered=0&offered=1",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert "Tick the listings to add" in response.text
        assert backend.decisions == []

    def test_rejecting_needs_no_ticks(self, client, backend):
        post(client, f"/agents/runs/{RUN_ID}/review", decision="reject", notes="wrong")
        assert backend.decisions == [{"decision": "reject", "notes": "wrong"}]

    def test_a_correction_carries_its_overview(self, client, backend):
        client.post(
            f"/agents/runs/{RUN_ID}/review",
            content="decision=correct&accepted=0&corrected_overview=Just+one",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert backend.decisions == [
            {"decision": "correct", "accepted": [0], "corrected_overview": "Just one"}
        ]

    def test_what_was_saved_and_what_was_not_are_both_shown(self, client, backend):
        backend.review_response = httpx.Response(
            200,
            json=run_view(
                "completed",
                saved=[{"accommodation_id": GROUNDED, "trip_id": "trip_sydney"}],
                save_errors=[
                    {
                        "accommodation_id": OTHER,
                        "code": "HTTP_422",
                        "message": "stay outside the trip",
                    }
                ],
            ),
        )
        html = post(client, f"/agents/runs/{RUN_ID}/review", decision="reject").text
        assert "Added to trip_sydney" in html
        assert "stay outside the trip" in html

    def test_a_refused_decision_shows_why_and_keeps_the_form(self, client, backend):
        backend.review_response = httpx.Response(
            409, json={"detail": "RUN_NOT_AWAITING_REVIEW: done"}
        )
        html = post(client, f"/agents/runs/{RUN_ID}/review", decision="reject").text
        assert "RUN_NOT_AWAITING_REVIEW" in html
        assert "Approve ticked" in html
