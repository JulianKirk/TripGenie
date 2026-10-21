"""Release 2: the multi-agent planning page, through the real backend to a fake
Multi-Agent Server."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_frontend_service.app import create_app as create_frontend_app
from student3_frontend_service.config import Settings as FrontendSettings

from tests.backend.test_agent_runs import (
    FERRY,
    FLIGHT,
    RUN_ID,
    TRIP,
    FakeMultiAgent,
    awaiting_run,
    search_trace,
)
from tests.frontend.conftest import StubItinerary, _build_backend


@pytest.fixture
def fake_server() -> FakeMultiAgent:
    return FakeMultiAgent()


@pytest.fixture
def agents_client(
    frontend_settings: FrontendSettings,
    database_path: Path,
    trips_transport: httpx.MockTransport,
    fake_server: FakeMultiAgent,
) -> Iterator[TestClient]:
    for backend_app in _build_backend(
        database_path,
        trips_transport,
        multi_agent_transport=httpx.MockTransport(fake_server.handle),
    ):
        app = create_frontend_app(
            frontend_settings,
            transport=httpx.ASGITransport(app=backend_app),
        )
        with TestClient(app) as test_client:
            yield test_client


def _collapsed(response: httpx.Response) -> str:
    return " ".join(response.text.split())


def test_the_agents_page_is_linked_and_explains_the_workflow(
    agents_client: TestClient,
) -> None:
    assert "Plan with agents" in agents_client.get("/").text

    text = _collapsed(agents_client.get("/agents"))

    assert "Plan transport with agents" in text
    assert "Planner" in text
    assert "Worker" in text
    assert "Reviewer" in text
    assert "You make the final decision" in text
    assert '<textarea id="question" name="question"' in text


def test_starting_a_run_redirects_to_its_page(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    response = agents_client.post(
        "/agents",
        data={
            "question": "Best way to Tasmania?",
            "origin": "Geelong",
            "trip_id": TRIP,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(f"/agents/runs/{RUN_ID}")
    (body,) = fake_server.started
    assert body["task"] == "Best way to Tasmania?"
    assert body["trip_id"] == TRIP


def test_a_working_run_polls_its_panel(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    fake_server.run["status"] = "working"

    page = _collapsed(agents_client.get(f"/agents/runs/{RUN_ID}"))
    panel = agents_client.get(f"/agents/runs/{RUN_ID}/panel")

    assert f'hx-get="http://testserver/agents/runs/{RUN_ID}/panel"' in page
    assert 'hx-trigger="every 2s"' in page
    assert "The Worker is looking transport up with the MCP tools" in page
    assert "Refresh now" in page
    assert panel.status_code == 200
    assert "<html" not in panel.text
    assert 'hx-trigger="every 2s"' in panel.text


def test_a_run_awaiting_review_shows_every_stage_and_the_decision_form(
    agents_client: TestClient,
) -> None:
    text = _collapsed(agents_client.get(f"/agents/runs/{RUN_ID}"))

    assert "hx-trigger" not in text
    assert "Waiting for your decision" in text
    assert "Find transport from Geelong to Tasmania for four." in text
    assert "Tools used &middot; 1 MCP call" in text
    assert "transport_search" in text
    assert "all ids came from tool results" in text
    assert "Supported by transport_search." in text
    assert "Availability may change." in text
    assert "The Spirit of Tasmania ferry is the only crossing." in text
    # Only the grounded option can be ticked; the invented one is labelled.
    assert 'name="accepted" value="0" checked' in text
    assert 'name="accepted" value="1"' not in text
    assert "not from a tool" in text
    assert 'name="traveller_count"' in text
    assert "Approve and add ticked" in text


def test_approving_adds_the_ticked_option_to_the_trip(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary: StubItinerary,
) -> None:
    response = agents_client.post(
        f"/agents/runs/{RUN_ID}/review",
        data={
            "decision": "approve",
            "offered": ["0"],
            "accepted": ["0"],
            "traveller_count": "4",
            "reviewer": "ronit",
            "notes": "Ferry it is",
        },
    )

    text = _collapsed(response)
    assert response.status_code == 200
    assert fake_server.reviews == [
        {"decision": "approve", "reviewer": "ronit", "notes": "Ferry it is"},
    ]
    assert "Human decision: approve" in text
    assert "Added <a href=" in text
    assert FERRY in text
    assert itinerary.pins[(TRIP, FERRY)]["traveller_count"] == 4


def test_approving_some_of_the_options_is_a_partial_acceptance(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary: StubItinerary,
) -> None:
    fake_server.run = awaiting_run(
        [
            {"transport_id": FERRY, "reason": "Ferry."},
            {"transport_id": FLIGHT, "reason": "Flight."},
        ],
        [search_trace(FERRY, FLIGHT)],
    )

    agents_client.post(
        f"/agents/runs/{RUN_ID}/review",
        data={
            "decision": "approve",
            "offered": ["0", "1"],
            "accepted": ["1"],
            "traveller_count": "2",
        },
    )

    assert fake_server.reviews[0]["decision"] == "partial"
    assert fake_server.reviews[0]["accepted_actions"] == [1]
    assert set(itinerary.pins) == {(TRIP, FLIGHT)}


def test_a_correction_replaces_the_answer(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    text = _collapsed(
        agents_client.post(
            f"/agents/runs/{RUN_ID}/review",
            data={
                "decision": "correct",
                "offered": ["0"],
                "accepted": ["0"],
                "traveller_count": "4",
                "corrected_overview": "Only the ferry crosses to Tasmania.",
            },
        ),
    )

    corrected = fake_server.reviews[0]["corrected_result"]
    assert corrected["overview"] == "Only the ferry crosses to Tasmania."
    assert "Answer you signed off" in text
    assert "Only the ferry crosses to Tasmania." in text


def test_rejecting_adds_nothing(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
    itinerary: StubItinerary,
) -> None:
    text = _collapsed(
        agents_client.post(
            f"/agents/runs/{RUN_ID}/review",
            data={"decision": "reject", "accepted": ["0"], "traveller_count": "4"},
        ),
    )

    assert fake_server.reviews[0]["decision"] == "reject"
    assert "Human decision: reject" in text
    assert itinerary.pins == {}


def test_an_incomplete_decision_is_shown_on_the_form(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    text = _collapsed(
        agents_client.post(
            f"/agents/runs/{RUN_ID}/review",
            data={"decision": "approve", "offered": ["0"], "accepted": ["0"]},
        ),
    )

    assert fake_server.reviews == []
    assert "VALIDATION_ERROR" in text
    assert "traveller_count" in text
    assert "Your decision" in text


def test_failed_checks_warn_before_the_decision(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    fake_server.run["checks"][0] |= {"passed": False, "detail": "id not returned"}

    text = _collapsed(agents_client.get(f"/agents/runs/{RUN_ID}"))

    assert "Some automatic checks failed" in text
    assert "id not returned" in text


def test_a_failed_run_explains_what_happened(
    agents_client: TestClient,
    fake_server: FakeMultiAgent,
) -> None:
    fake_server.run["status"] = "failed"
    fake_server.run["error"] = {"code": "RUN_TIMEOUT", "message": "Too slow."}

    text = _collapsed(agents_client.get(f"/agents/runs/{RUN_ID}"))

    assert "The run failed: RUN_TIMEOUT" in text
    assert "Your decision" not in text


def test_an_unknown_run_id_is_reported(agents_client: TestClient) -> None:
    text = _collapsed(agents_client.get("/agents/runs/not-a-run"))

    assert "RUN_NOT_FOUND" in text


def test_the_page_says_when_multi_agent_is_disabled(client: TestClient) -> None:
    text = _collapsed(client.post("/agents", data={"question": "Any way to Sydney?"}))

    assert "MULTI_AGENT_DISABLED" in text
    assert "disabled in this environment" in text
    assert "Browsing, comparing and planning still work as normal." in text
