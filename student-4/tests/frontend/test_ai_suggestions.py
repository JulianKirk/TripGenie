from __future__ import annotations

import html
import json
import re

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import DETAIL, TRIP_ID, FakeBackend


def frontend(backend: FakeBackend) -> TestClient:
    return TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    )


def test_index_offers_prompt_trip_context_and_immediate_progress(
    backend: FakeBackend,
) -> None:
    backend.overrides[("GET", "/activity/trips")] = httpx.Response(
        200,
        json={
            "available": True,
            "trips": [
                {
                    "id": TRIP_ID,
                    "name": "Sydney Getaway",
                    "destination": "Sydney",
                    "start_date": "2027-04-01",
                    "end_date": "2027-04-03",
                    "traveller_count": 2,
                    "status": "planned",
                    "notes": "Prefer a relaxed first day.",
                }
            ],
        },
    )

    text = frontend(backend).get("/").text

    assert "AI activity suggestions" in text
    assert 'name="question"' in text
    assert 'name="trip_id"' in text
    assert "Sydney Getaway" in text
    assert "Understanding your request" in text
    assert "nothing is added to a trip" in text


def test_plan_fragment_shows_search_and_automatically_starts_evaluation(
    backend: FakeBackend,
) -> None:
    backend.overrides[("POST", "/activity/recommendations/plan")] = httpx.Response(
        200,
        json={
            "question": "Outdoor ideas",
            "trip_id": TRIP_ID,
            "query": {
                "location": {"country": "australia", "city": "sydney"},
                "categories": {"codes": ["OUTDOOR"], "match": "ANY"},
                "party_size": 2,
                "limit": 20,
                "offset": 0,
            },
            "summary": "outdoor activities in Sydney for two travellers",
            "trip_context_available": True,
        },
    )

    response = frontend(backend).post(
        "/suggestions/plan",
        data={"question": "Outdoor ideas", "trip_id": TRIP_ID},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert (
        "Searching for outdoor activities in Sydney for two travellers" in response.text
    )
    assert 'hx-post="/suggestions/evaluate"' in response.text
    assert 'hx-trigger="load"' in response.text
    assert "Evaluating the activities that match" in response.text


def test_evaluation_fragment_distinguishes_matches_from_ai_shortlist(
    backend: FakeBackend,
) -> None:
    backend.overrides[("POST", "/activity/recommendations/evaluate")] = httpx.Response(
        200,
        json={
            "status": "complete",
            "attempt": 1,
            "query": {
                "categories": {"codes": ["OUTDOOR"], "match": "ANY"},
                "limit": 20,
                "offset": 0,
            },
            "summary": "outdoor activities",
            "matched_count": 8,
            "evaluated_count": 8,
            "recommended": [
                {
                    "reason": "It fits the outdoor request and takes two hours.",
                    "activity": DETAIL,
                }
            ],
            "overview": "One activity is a particularly strong fit.",
            "considerations": ["External booking is required."],
            "disclaimer": "Review details before adding it.",
            "run_id": "run-1",
            "model": "qwen2.5:3b",
            "provider": "ollama",
        },
    )
    state = json.dumps(
        {
            "question": "Outdoor ideas",
            "query": {"categories": {"codes": ["OUTDOOR"], "match": "ANY"}},
            "summary": "outdoor activities",
            "attempt": 1,
        }
    )

    response = frontend(backend).post(
        "/suggestions/evaluate",
        data={"state": state},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "8 activities matched the search; AI shortlisted 1" in response.text
    assert "AI shortlist" in response.text
    assert "It fits the outdoor request" in response.text
    assert "Sydney Harbour guided walk" in response.text
    assert "Review and add to trip" in response.text
    assert "Nothing has been saved" in response.text
    assert 'hx-swap-oob="true"' in response.text


def test_retry_fragment_explains_changed_filters_and_runs_only_attempt_two(
    backend: FakeBackend,
) -> None:
    backend.overrides[("POST", "/activity/recommendations/evaluate")] = httpx.Response(
        200,
        json={
            "status": "retry",
            "attempt": 2,
            "query": {"duration_minutes": {"max": 180}, "limit": 20, "offset": 0},
            "summary": "activities lasting up to three hours",
            "matched_count": 0,
            "evaluated_count": 0,
            "recommended": [],
            "overview": "The first search was too narrow.",
            "considerations": [],
            "disclaimer": "Review the revised search.",
            "revision_explanation": "Broadening duration from one to three hours.",
            "run_id": "run-1",
            "model": "qwen2.5:3b",
            "provider": "ollama",
        },
    )
    state = json.dumps(
        {
            "question": "A short activity",
            "query": {"duration_minutes": {"max": 60}},
            "summary": "activities lasting up to one hour",
            "attempt": 1,
        }
    )

    text = frontend(backend).post("/suggestions/evaluate", data={"state": state}).text

    assert "No strong matches" in text
    assert "Broadening duration from one to three hours" in text
    assert "Searching again for activities lasting up to three hours" in text
    assert 'hx-trigger="load"' in text
    assert "attempt&#34;:2" in text


def test_invalid_carried_query_is_rejected_before_backend_call(
    backend: FakeBackend,
) -> None:
    state = json.dumps(
        {
            "question": "Outdoor ideas",
            "query": {"party_size": "two"},
            "summary": "outdoor activities",
            "attempt": 1,
        }
    )

    response = frontend(backend).post("/suggestions/evaluate", data={"state": state})

    assert "suggestion request is invalid" in response.text
    assert not any(
        request.url.path == "/activity/recommendations/evaluate"
        for request in backend.requests
    )


def test_category_refresh_failure_does_not_replace_existing_filters(
    backend: FakeBackend,
) -> None:
    backend.overrides[("POST", "/activity/recommendations/evaluate")] = httpx.Response(
        200,
        json={
            "status": "no_match",
            "attempt": 1,
            "query": {"limit": 20, "offset": 0},
            "summary": "outdoor activities",
            "matched_count": 0,
            "evaluated_count": 0,
            "recommended": [],
            "overview": "No suitable activity was found.",
            "considerations": [],
            "disclaimer": "Try refining your request.",
            "run_id": "run-1",
            "model": "qwen2.5:3b",
            "provider": "ollama",
        },
    )
    backend.overrides[("GET", "/activity/categories")] = httpx.Response(503)
    state = json.dumps(
        {
            "question": "Outdoor ideas",
            "query": {},
            "summary": "outdoor activities",
            "attempt": 1,
        }
    )

    response = frontend(backend).post("/suggestions/evaluate", data={"state": state})

    assert "No suitable activity found" in response.text
    assert 'hx-swap-oob="true"' not in response.text


def test_availability_window_round_trips_from_plan_to_evaluation(
    backend: FakeBackend,
) -> None:
    query = {
        "availability": {
            "date": "2027-04-02",
            "start_time": "09:00",
            "end_time": "11:00",
        },
        "limit": 20,
        "offset": 0,
    }
    backend.overrides[("POST", "/activity/recommendations/plan")] = httpx.Response(
        200,
        json={
            "question": "A Friday morning activity",
            "query": query,
            "summary": "Friday morning activities",
            "trip_context_available": False,
        },
    )
    planned = frontend(backend).post(
        "/suggestions/plan", data={"question": "A Friday morning activity"}
    )
    match = re.search(r'name="state" value="([^"]+)"', planned.text)
    assert match is not None
    state = html.unescape(match.group(1))

    backend.overrides[("POST", "/activity/recommendations/evaluate")] = httpx.Response(
        200,
        json={
            "status": "no_match",
            "attempt": 1,
            "query": query,
            "summary": "Friday morning activities",
            "matched_count": 0,
            "evaluated_count": 0,
            "recommended": [],
            "overview": "No suitable activity was found.",
            "considerations": [],
            "disclaimer": "Try another time.",
            "run_id": "run-1",
            "model": "qwen2.5:3b",
            "provider": "ollama",
        },
    )
    evaluated = frontend(backend).post("/suggestions/evaluate", data={"state": state})

    assert "No suitable activity found" in evaluated.text
    evaluation_request = next(
        request
        for request in backend.requests
        if request.url.path == "/activity/recommendations/evaluate"
    )
    evaluation_body = json.loads(evaluation_request.content)
    assert evaluation_body["query"]["availability"] == query["availability"]
