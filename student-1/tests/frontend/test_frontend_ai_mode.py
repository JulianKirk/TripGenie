from __future__ import annotations

import html
import json
import re

import pytest

from .conftest import create_item_form_data, data_response, error_response

HTMX_HEADERS = {"HX-Request": "true"}


def test_ai_form_submission_via_htmx_returns_draft_results_without_persisting(
    client,
    backend_api,
) -> None:
    starting_item_ids = set(backend_api.items)

    response = client.post(
        "/trips/trip_2027_sydney_getaway/ai-suggestions",
        data={
            "requested_date": "2027-04-02",
            "goal": "Plan a gentle afternoon after the harbour walk.",
            "interests": "quiet cafes, water views",
            "constraints": "avoid duplicate activities",
            "view_date": "2027-04-02",
            "view_category": "",
        },
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 200
    assert (
        response.headers["HX-Push-Url"]
        == "/trips/trip_2027_sydney_getaway?date=2027-04-02"
    )
    assert "Draft results" in response.text
    assert "Draft" in response.text
    assert "Approval required" in response.text
    assert "persisted=false" in response.text
    assert "Review and save via CRUD" in response.text
    assert "ai_demo_run_01" in response.text
    assert "runtime_ai_suggestions_v1.md" in response.text
    assert len(backend_api.ai_requests) == 1
    assert set(backend_api.items) == starting_item_ids


def test_ai_empty_state_renders_without_breaking_trip_page(client, backend_api) -> None:
    backend_api.ai_responses.append(
        data_response(
            200,
            {
                "trip_id": "trip_2027_sydney_getaway",
                "requested_date": "2027-04-02",
                "model": "qwen2.5:0.5b",
                "prompt_asset": "runtime_ai_suggestions_v1.md",
                "run_id": "ai_empty_run_01",
                "correlation_id": "ai_empty_run_01",
                "attempt_count": 1,
                "persisted": False,
                "approval_required": True,
                "suggestions": [],
            },
        ),
    )

    response = client.post(
        "/trips/trip_2027_sydney_getaway/ai-suggestions",
        data={
            "requested_date": "2027-04-02",
            "goal": "See the empty suggestion state.",
            "interests": "",
            "constraints": "",
            "view_date": "",
            "view_category": "",
        },
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 200
    assert "No draft suggestions matched this request." in response.text
    assert (
        "Try broadening the goal or relaxing constraints for 2027-04-02."
        in response.text
    )


def test_ai_error_preserves_form_values_and_shows_backend_validation(
    client,
    backend_api,
) -> None:
    backend_api.ai_responses.append(
        error_response(
            502,
            "AI_OUTPUT_INVALID",
            (
                "AI-generated suggestions could not be validated "
                "after 2 attempt(s)."
            ),
            [
                {
                    "field": "ai_suggestions",
                    "issue": "runtime validation retries were exhausted",
                },
            ],
        ),
    )

    response = client.post(
        "/trips/trip_2027_sydney_getaway/ai-suggestions",
        data={
            "requested_date": "2027-04-02",
            "goal": "Keep this goal visible.",
            "interests": "Keep these interests visible.",
            "constraints": "Keep these constraints visible.",
            "view_date": "2027-04-02",
            "view_category": "meal",
        },
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 502
    assert (
        response.headers["HX-Push-Url"]
        == "/trips/trip_2027_sydney_getaway?date=2027-04-02&category=meal"
    )
    assert "AI-generated suggestions could not be validated" in response.text
    assert "runtime validation retries were exhausted" in response.text
    assert "Keep this goal visible." in response.text
    assert "Keep these interests visible." in response.text
    assert "Keep these constraints visible." in response.text
    assert 'value="2027-04-02"' in response.text
    assert '<option value="meal" selected>' in response.text


def test_ai_review_control_uses_post_handoff_without_sensitive_query_string(
    client,
    backend_api,
) -> None:
    response = client.post(
        "/trips/trip_2027_sydney_getaway/ai-suggestions",
        data={
            "requested_date": "2027-04-02",
            "goal": "Plan a gentle afternoon after the harbour walk.",
            "interests": "quiet cafes, water views",
            "constraints": "avoid duplicate activities",
            "view_date": "",
            "view_category": "",
        },
        headers=HTMX_HEADERS,
    )

    review_form_match = re.search(
        (
            r'(<form action="/trips/trip_2027_sydney_getaway/items/new" '
            r'method="post">.*?Review and save via CRUD.*?</form>)'
        ),
        response.text,
        re.S,
    )
    assert review_form_match is not None
    review_form = review_form_match.group(1)

    assert 'name="draft_payload"' in review_form
    assert 'href="' not in review_form
    assert "title=Waterside" not in review_form
    assert "location=Barangaroo" not in review_form
    assert "description=Relaxed" not in review_form
    assert "notes=Keep" not in review_form
    assert "ai_rationale=" not in review_form


def test_ai_review_post_prefills_item_form_and_requires_manual_save(
    client,
    backend_api,
) -> None:
    suggestions_response = client.post(
        "/trips/trip_2027_sydney_getaway/ai-suggestions",
        data={
            "requested_date": "2027-04-02",
            "goal": "Plan a gentle afternoon after the harbour walk.",
            "interests": "quiet cafes, water views",
            "constraints": "avoid duplicate activities",
            "view_date": "",
            "view_category": "",
        },
        headers=HTMX_HEADERS,
    )
    payload_match = re.search(
        (
            r'<form action="/trips/trip_2027_sydney_getaway/items/new" '
            r'method="post">.*?name="draft_payload" value="([^"]+)".*?'
            r"Review and save via CRUD.*?</form>"
        ),
        suggestions_response.text,
        re.S,
    )
    assert payload_match is not None
    draft_payload = html.unescape(payload_match.group(1))

    form_response = client.post(
        "/trips/trip_2027_sydney_getaway/items/new",
        data={"draft_payload": draft_payload},
        headers=HTMX_HEADERS,
    )

    assert form_response.status_code == 200
    assert 'id="app-shell"' in form_response.text
    assert AI_REVIEW_NOTICE_SNIPPET in form_response.text
    assert 'value="Waterside Lunch"' in form_response.text
    assert 'value="12:30"' in form_response.text
    assert 'value="14:00"' in form_response.text
    assert "item_generated_01" not in backend_api.items

    save_response = client.post(
        "/trips/trip_2027_sydney_getaway/items",
        data={
            "ai_draft": "true",
            "ai_rationale": "Creates a calm midday stop.",
            **create_item_form_data(
                id="item_generated_01",
                date="2027-04-02",
                start_time="12:30",
                end_time="14:00",
                title="Waterside Lunch",
                location="Barangaroo",
                description="Relaxed lunch with harbour views.",
                category="meal",
                notes="Keep it flexible.",
            ),
        },
        headers=HTMX_HEADERS,
    )

    assert save_response.status_code == 200
    assert "Waterside Lunch" in save_response.text
    assert "item_generated_01" in backend_api.items


@pytest.mark.parametrize(
    "draft_payload",
    [
        "{not json",
        json.dumps(
            {
                "date": "2027-04-02",
                "start_time": "25:99",
                "end_time": "14:00",
                "title": "Waterside Lunch",
                "location": "Barangaroo",
                "description": "Relaxed lunch with harbour views.",
                "category": "meal",
                "notes": "Keep it flexible.",
                "ai_rationale": "Creates a calm midday stop.",
            }
        ),
    ],
)
def test_ai_review_post_rejects_malformed_or_tampered_handoff_safely(
    client,
    backend_api,
    draft_payload: str,
) -> None:
    starting_item_ids = set(backend_api.items)

    response = client.post(
        "/trips/trip_2027_sydney_getaway/items/new",
        data={"draft_payload": draft_payload},
    )

    assert response.status_code == 422
    assert "The AI draft could not be prepared for review." in response.text
    assert set(backend_api.items) == starting_item_ids


def test_ai_mode_absence_error_does_not_break_normal_trip_pages(
    client,
    backend_api,
) -> None:
    backend_api.ai_responses.append(
        error_response(
            503,
            "DEPENDENCY_UNAVAILABLE",
            "Shared AI-Mode service is unavailable.",
            [{"field": "ai_mode", "issue": "connection failed"}],
        ),
    )

    ai_response = client.post(
        "/trips/trip_2027_sydney_getaway/ai-suggestions",
        data={
            "requested_date": "2027-04-02",
            "goal": "Plan a gentle afternoon.",
            "interests": "",
            "constraints": "",
            "view_date": "",
            "view_category": "",
        },
        headers=HTMX_HEADERS,
    )
    detail_response = client.get("/trips/trip_2027_sydney_getaway")
    edit_response = client.get("/trips/trip_2027_sydney_getaway/edit")

    assert ai_response.status_code == 503
    assert "Shared AI-Mode service is unavailable." in ai_response.text
    assert detail_response.status_code == 200
    assert "Sydney Getaway" in detail_response.text
    assert edit_response.status_code == 200
    assert 'value="Sydney Getaway"' in edit_response.text


AI_REVIEW_NOTICE_SNIPPET = "You are reviewing an AI-generated draft."
