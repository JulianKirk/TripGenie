from __future__ import annotations

import json

import httpx
import pytest

from .conftest import data_response, error_response

HTMX_HEADERS = {"HX-Request": "true"}
TRIP_ID = "trip_2027_sydney_getaway"
RUN_ID = "magent_0123456789ab"
START_URL = f"/trips/{TRIP_ID}/multi-agent-plan"
VIEW_URL = f"{START_URL}/{RUN_ID}"
REVIEW_URL = f"{VIEW_URL}/review"


def plan_item(index: int, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "index": index,
        "date": "2027-04-02",
        "start_time": "18:00",
        "end_time": "20:00",
        "title": "Opera night",
        "location": "Sydney Opera House",
        "description": "Evening performance.",
        "category": "activity",
        "source_id": "act_opera",
        "problems": [],
        "warnings": [],
    }
    item.update(overrides)
    return item


def plan_run(status: str = "awaiting_human", **overrides: object) -> dict:
    payload: dict[str, object] = {
        "trip_id": TRIP_ID,
        "run_id": RUN_ID,
        "correlation_id": "student1-plan-abc",
        "status": status,
        "active": status in {"planning", "working", "reviewing"},
        "request": "Plan my itinerary",
        "created_at": "2027-03-01T10:00:00Z",
        "updated_at": "2027-03-01T10:01:00Z",
        "attempts": 1,
        "plan": None,
        "steps": [],
        "checks": [],
        "review": None,
        "summary": None,
        "items": [],
        "approved_items": [],
        "human": None,
        "error": None,
        "persistence": None,
    }
    if status == "awaiting_human":
        payload.update(
            plan={
                "goal": "Fit saved activities into the trip",
                "steps": ["Read the trip"],
                "required_evidence": ["saved activities"],
                "tools_to_use": ["trip_get_context"],
                "success_criteria": ["dates inside the trip"],
            },
            steps=[
                {
                    "agent": "worker",
                    "attempt": 1,
                    "status": "completed",
                    "duration_ms": 900,
                    "model": "qwen3:8b",
                    "tools": [
                        {
                            "tool": "trip_get_context",
                            "arguments": {"trip_id": TRIP_ID},
                            "status": "success",
                            "duration_ms": 30,
                            "data": {"name": "Sydney Getaway"},
                            "error": None,
                        },
                    ],
                    "error": None,
                },
            ],
            checks=[
                {
                    "name": "dates_within_trip",
                    "passed": False,
                    "blocking": True,
                    "detail": "item 2 is outside the trip",
                },
            ],
            review={
                "verdict": "revise",
                "summary": "One item is outside the trip.",
                "issues": ["Item 2 date"],
                "risks": ["Clash with Harbour Walk"],
                "recommendations": ["Move item 2"],
            },
            summary="Two evenings planned.",
            items=[
                plan_item(0, warnings=["Overlaps 'Harbour Walk' at 09:00."]),
                plan_item(
                    1,
                    date="2027-05-01",
                    title="Beach day",
                    problems=["date must fall between 2027-04-01 and 2027-04-03"],
                ),
            ],
        )
    payload.update(overrides)
    return payload


def decided_run(decision: str, outcome: str, **persistence: object) -> dict:
    return plan_run(
        "rejected" if decision == "reject" else "completed",
        human={
            "decision": decision,
            "reviewer": "traveller",
            "notes": None,
            "decided_at": "2027-03-01T10:05:00Z",
            "accepted_actions": [],
        },
        approved_items=[] if decision == "reject" else [plan_item(0)],
        persistence={
            "outcome": outcome,
            "saved": [],
            "already_saved": [],
            "failed": [],
            **persistence,
        },
    )


class PlanBackend:
    """Answers the multi-agent routes; everything else hits the fake API."""

    def __init__(self, backend_api) -> None:
        self.backend_api = backend_api
        self.responses: dict[str, httpx.Response | Exception] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/multi-agent-plan" not in path:
            return self.backend_api.handle(request)
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        kind = (
            "review"
            if path.endswith("/review")
            else "get"
            if request.method == "GET"
            else "start"
        )
        response = self.responses[kind]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def plan_backend(backend_api) -> PlanBackend:
    return PlanBackend(backend_api)


@pytest.fixture
def plan_client(client_factory, plan_backend):
    with client_factory(plan_backend) as test_client:
        yield test_client


def test_trip_page_offers_the_planner(client) -> None:
    response = client.get(f"/trips/{TRIP_ID}")

    assert response.status_code == 200
    assert 'id="multi-agent-panel"' in response.text
    assert f'action="http://testserver{START_URL}"' in response.text
    assert "Nothing is saved until you approve" in response.text


def test_start_renders_a_polling_panel(plan_client, plan_backend) -> None:
    plan_backend.responses["start"] = data_response(202, plan_run("working"))

    response = plan_client.post(
        START_URL, data={"request": " Keep mornings free "}, headers=HTMX_HEADERS
    )

    assert response.status_code == 200
    assert plan_backend.calls == [
        ("POST", f"/api{START_URL}", {"request": "Keep mornings free"}),
    ]
    text = response.text
    assert text.lstrip().startswith('<section\n  id="multi-agent-panel"')
    assert f'hx-get="http://testserver{VIEW_URL}"' in text
    assert 'hx-trigger="every 3s"' in text and "data-preserve-focus" in text
    assert 'aria-current="step"' in text
    # A no-JS fallback for the polling.
    assert f'<a href="http://testserver{VIEW_URL}">Refresh status</a>' in text


def test_blank_request_uses_the_backend_default(plan_client, plan_backend) -> None:
    plan_backend.responses["start"] = data_response(202, plan_run("planning"))

    plan_client.post(START_URL, data={"request": "  "}, headers=HTMX_HEADERS)

    assert plan_backend.calls[0][2] == {}


def test_awaiting_plan_shows_evidence_checks_and_all_decisions(
    plan_client, plan_backend
) -> None:
    plan_backend.responses["get"] = data_response(200, plan_run())

    response = plan_client.get(VIEW_URL, headers=HTMX_HEADERS)

    assert response.status_code == 200
    text = response.text
    assert "hx-trigger" not in text  # polling stops once the agents are done
    for expected in (
        "Fit saved activities into the trip",
        "<code>trip_get_context</code>",
        "<code>dates_within_trip</code>",
        "Verdict: revise",
        "Clash with Harbour Walk",
        "Overlaps &#39;Harbour Walk&#39; at 09:00.",
        "date must fall between 2027-04-01 and 2027-04-03",
        f'action="http://testserver{REVIEW_URL}"',
    ):
        assert expected in text
    for decision in ("approve", "partial", "correct", "reject"):
        assert f'name="decision" value="{decision}"' in text
    # Item 1 can be saved and is ticked; item 2 has a blocking problem.
    assert 'name="selected" value="0" checked' in text
    assert 'name="selected" value="1">' in text


def test_untrusted_text_is_escaped(plan_client, plan_backend) -> None:
    hostile = "<script>alert(1)</script>"
    plan_backend.responses["get"] = data_response(
        200,
        plan_run(summary=hostile, items=[plan_item(0, title=hostile)]),
    )

    response = plan_client.get(VIEW_URL, headers=HTMX_HEADERS)

    assert hostile not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ({"decision": "approve", "selected": ["0"]}, {"decision": "approve"}),
        (
            {"decision": "reject", "notes": " Not this time "},
            {"decision": "reject", "notes": "Not this time"},
        ),
        (
            {"decision": "partial", "selected": ["1", "0", "0"]},
            {"decision": "partial", "accepted_items": [0, 1]},
        ),
        (
            {
                "decision": "correct",
                "selected": ["1"],
                "item-1-date": "2027-04-03",
                "item-1-start_time": "",
                "item-1-title": "Beach day",
                "item-1-category": "activity",
                "item-1-source_id": "act_beach",
                "item-0-title": "Not selected",
            },
            {
                "decision": "correct",
                "corrected_items": [
                    {
                        "date": "2027-04-03",
                        "title": "Beach day",
                        "category": "activity",
                        "source_id": "act_beach",
                    },
                ],
            },
        ),
    ],
)
def test_each_decision_posts_its_review(
    plan_client, plan_backend, form, expected
) -> None:
    plan_backend.responses["review"] = data_response(
        200, decided_run(expected["decision"], "saved")
    )

    plan_client.post(REVIEW_URL, data=form, headers=HTMX_HEADERS)

    assert plan_backend.calls == [("POST", f"/api{REVIEW_URL}", expected)]


def test_saved_and_rejected_outcomes_are_explicit(plan_client, plan_backend) -> None:
    saved = {"index": 0, "id": f"item_{RUN_ID}_0", "title": "Opera night"}
    plan_backend.responses["review"] = data_response(
        200, decided_run("approve", "saved", saved=[saved])
    )
    approved = plan_client.post(
        REVIEW_URL, data={"decision": "approve"}, headers=HTMX_HEADERS
    )
    plan_backend.responses["review"] = data_response(
        200, decided_run("reject", "rejected")
    )
    rejected = plan_client.post(
        REVIEW_URL, data={"decision": "reject"}, headers=HTMX_HEADERS
    )

    assert "All 1 approved item(s) are on your itinerary." in approved.text
    assert "Item 1: Opera night" in approved.text
    assert "Retry saving" not in approved.text
    assert "Nothing was saved: you rejected this plan." in rejected.text
    assert "Plan again" in rejected.text


def test_partial_save_is_never_reported_as_complete(plan_client, plan_backend) -> None:
    plan_backend.responses["review"] = data_response(
        200,
        decided_run(
            "partial",
            "partially_saved",
            saved=[{"index": 0, "id": f"item_{RUN_ID}_0", "title": "Opera night"}],
            failed=[
                {
                    "index": 1,
                    "id": f"item_{RUN_ID}_1",
                    "code": "DEPENDENCY_UNAVAILABLE",
                    "message": "Database API is unavailable.",
                },
            ],
        ),
    )

    response = plan_client.post(
        REVIEW_URL,
        data={"decision": "partial", "selected": ["0", "1"]},
        headers=HTMX_HEADERS,
    )

    text = response.text
    assert "Only 1 of 2 approved items are on your itinerary." in text
    assert "Item 2 (DEPENDENCY_UNAVAILABLE): Database API is unavailable." in text
    assert "All " not in text
    # The retry repeats the recorded decision, which saves only what is missing.
    assert '<input type="hidden" name="decision" value="partial">' in text
    assert "Retry saving the missing items" in text


def test_refused_correction_keeps_the_plan_and_the_edits(
    plan_client, plan_backend
) -> None:
    plan_backend.responses["review"] = error_response(
        422,
        "VALIDATION_ERROR",
        "Request validation failed.",
        [{"field": "corrected_items.0.date", "issue": "must fall in the trip"}],
    )
    plan_backend.responses["get"] = data_response(200, plan_run())

    response = plan_client.post(
        REVIEW_URL,
        data={
            "decision": "correct",
            "selected": ["1"],
            "item-1-date": "2027-06-01",
            "item-1-title": "Beach <day>",
            "item-1-category": "activity",
        },
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 422
    text = response.text
    # The detail names the item the traveller edited, not its list position.
    assert "Item 2 date: must fall in the trip" in text
    assert 'value="2027-06-01"' in text and "Beach &lt;day&gt;" in text
    assert 'name="selected" value="1" checked' in text
    assert 'name="selected" value="0">' in text
    assert [call[0] for call in plan_backend.calls] == ["POST", "GET"]


def test_already_decided_plan_shows_the_recorded_decision(
    plan_client, plan_backend
) -> None:
    plan_backend.responses["review"] = error_response(
        409,
        "MULTI_AGENT_ALREADY_DECIDED",
        "This plan was already decided (reject).",
        [{"field": "decision", "issue": "reject"}],
    )
    plan_backend.responses["get"] = data_response(
        200, decided_run("reject", "rejected")
    )

    response = plan_client.post(
        REVIEW_URL, data={"decision": "approve"}, headers=HTMX_HEADERS
    )

    assert response.status_code == 409
    assert "the recorded decision stands" in response.text
    assert "Nothing was saved: you rejected this plan." in response.text
    assert 'value="approve"' not in response.text


@pytest.mark.parametrize(
    ("response", "status", "headline"),
    [
        (
            error_response(
                503, "MULTI_AGENT_DISABLED", "Multi-agent planning is disabled."
            ),
            503,
            "The multi-agent itinerary planner is not enabled in this environment.",
        ),
        (
            error_response(
                503, "DEPENDENCY_UNAVAILABLE", "Multi-Agent Server is unavailable."
            ),
            503,
            "The service behind this panel is unavailable right now.",
        ),
        (
            httpx.ConnectError("connection refused"),
            503,
            "The service behind this panel is unavailable right now.",
        ),
        (
            data_response(202, {"run_id": RUN_ID}),
            502,
            "The service returned a response TripGenie could not read.",
        ),
    ],
)
def test_start_failures_render_in_the_panel(
    plan_client, plan_backend, response, status, headline
) -> None:
    plan_backend.responses["start"] = response

    result = plan_client.post(START_URL, data={}, headers=HTMX_HEADERS)

    assert result.status_code == status
    assert headline in result.text
    assert "Trip and itinerary editing still works." in result.text
    assert "Plan my itinerary</button>" in result.text


@pytest.mark.parametrize("htmx", [True, False])
def test_switched_off_planner_is_hidden_and_a_stale_post_gets_no_form(
    plan_client, plan_backend, backend_api, htmx
) -> None:
    backend_api.ai_features["multi_agent"] = False
    assert 'id="multi-agent-panel"' not in plan_client.get(f"/trips/{TRIP_ID}").text

    plan_backend.responses["start"] = error_response(
        503, "MULTI_AGENT_DISABLED", "Multi-agent planning is disabled."
    )
    response = plan_client.post(
        START_URL, data={}, headers=HTMX_HEADERS if htmx else {}
    )

    assert response.status_code == 503
    assert "The multi-agent itinerary planner is not enabled" in response.text
    assert "Plan my itinerary</button>" not in response.text
    assert "Nothing is saved until you approve" not in response.text


def test_a_revised_run_shows_each_attempt_and_the_failed_step(
    plan_client, plan_backend
) -> None:
    run = plan_run(attempts=2)
    worker = run["steps"][0]
    run["steps"] = [
        {
            **worker,
            "status": "failed",
            "tools": [],
            "error": "AI-Mode returned bad JSON.",
        },
        {**worker, "agent": "planner", "attempt": 2, "tools": []},
        {**worker, "attempt": 2},
    ]
    plan_backend.responses["get"] = data_response(200, run)

    text = plan_client.get(VIEW_URL, headers=HTMX_HEADERS).text

    assert "2 attempt(s)" in text
    assert "Agent steps and tool evidence (3)" in text
    assert '<span class="badge badge--danger">Failed</span>' in text
    assert "<strong>AI-Mode returned bad JSON.</strong>" in text
    assert text.count("attempt 2 ·") == 2
    assert 'name="decision" value="approve"' in text


def test_failed_poll_stops_polling_and_offers_a_recheck(
    plan_client, plan_backend
) -> None:
    plan_backend.responses["get"] = error_response(
        404, "NOT_FOUND", "Plan not found.", [{"field": "run_id", "issue": RUN_ID}]
    )

    response = plan_client.get(VIEW_URL, headers=HTMX_HEADERS)

    assert response.status_code == 404
    assert "This trip or plan could not be found." in response.text
    assert "hx-trigger" not in response.text
    assert "Check this plan again" in response.text


def test_invalid_references_never_reach_the_backend(plan_client, plan_backend) -> None:
    bad_run = plan_client.get(f"{START_URL}/not_a_run", headers=HTMX_HEADERS)
    bad_index = plan_client.post(
        REVIEW_URL,
        data={"decision": "partial", "selected": ["x"]},
        headers=HTMX_HEADERS,
    )

    assert bad_run.status_code == 422
    assert bad_index.status_code == 422
    assert "selected: must be drafted item numbers" in bad_index.text
    assert plan_backend.calls == []


def test_without_javascript_the_status_page_is_a_full_trip_page(
    plan_client, plan_backend
) -> None:
    plan_backend.responses["get"] = data_response(200, plan_run("reviewing"))

    response = plan_client.get(VIEW_URL)

    assert response.status_code == 200
    assert "<html" in response.text
    assert "Sydney Getaway" in response.text
    assert "Reviewer: checking the draft" in response.text
