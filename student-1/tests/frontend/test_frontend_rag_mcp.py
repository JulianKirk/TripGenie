from __future__ import annotations

import json

import httpx
import pytest

from .conftest import data_response, error_response

HTMX_HEADERS = {"HX-Request": "true"}
TRIP_ID = "trip_2027_sydney_getaway"
RAG_URL = f"/trips/{TRIP_ID}/rag-query"
MCP_URL = f"/trips/{TRIP_ID}/mcp-options"


class FeatureBackend:
    """Serves one canned RAG/MCP response; everything else hits the fake API."""

    def __init__(self, backend_api, response: httpx.Response | Exception) -> None:
        self.backend_api = backend_api
        self.response = response
        self.bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/rag-query", "/mcp-options")):
            self.bodies.append(json.loads(request.content))
            if isinstance(self.response, Exception):
                raise self.response
            return self.response
        return self.backend_api.handle(request)


def rag_answer(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "trip_id": TRIP_ID,
        "answer": "Itinerary items must fall within the trip dates.",
        "confidence_category": "high",
        "insufficient_context": False,
        "citations": [
            {
                "source_id": "student1_backend_readme",
                "title": "Student 1 backend",
                "section": "Itinerary rules",
                "path": "student-1/backend/README.md",
                "chunk_id": "chunk_001",
                "excerpt": "An item's date must be between start_date and end_date.",
            },
        ],
        "retrieval": {"requested_top_k": 5, "returned_chunks": 1, "maximum_score": 0.8},
        "run_id": "rag_run_01",
        "correlation_id": "student1-rag-abc",
    }
    payload.update(overrides)
    return payload


INSUFFICIENT = rag_answer(
    answer="Something the model made up.",
    confidence_category="insufficient_context",
    insufficient_context=True,
    citations=[],
)


def tool(name: str, status: str, **fields: object) -> dict[str, object]:
    return {
        "tool": name,
        "arguments": fields.pop("arguments", {"trip_id": TRIP_ID}),
        "status": status,
        "data": None,
        "error": None,
        "reason": None,
        "correlation_id": None,
        **fields,
    }


def mcp_options(results: list[dict[str, object]], country: str | None) -> dict:
    counts = {
        s: sum(r["status"] == s for r in results) for s in ("ok", "error", "skipped")
    }
    return {
        "trip_id": TRIP_ID,
        "correlation_id": "student1-mcp-abc",
        "location": {"city": "Sydney", "country": country},
        "persisted": False,
        "results": results,
        "summary": counts,
    }


ALL_OK = [
    tool(
        "trip_get_context",
        "ok",
        data={
            "name": "Sydney Getaway",
            "destination": "Sydney",
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
            "traveller_count": 2,
        },
    ),
    tool(
        "accommodations_search",
        "ok",
        arguments={"country": "Australia", "city": "Sydney", "limit": 5},
        data={
            "items": [
                {
                    "id": "a1",
                    "name": "Harbour Hotel",
                    "type": "HOTEL",
                    "price_per_night": 210,
                },
            ],
            "count": 1,
            "truncated": False,
        },
    ),
    tool(
        "activities_search",
        "ok",
        data={
            "items": [
                {
                    "id": "x1",
                    "name": "Bridge Climb",
                    "price": 300,
                    "pricing_basis": "PER_PERSON",
                },
            ],
            "count": 1,
            "truncated": True,
        },
    ),
    tool(
        "transport_search",
        "ok",
        data={
            "items": [
                {
                    "id": "t1",
                    "type": "FERRY",
                    "provider": "Harbour Ferries",
                    "origin": "Manly",
                    "destination": "Sydney",
                    "price": 9,
                    "pricing_basis": "PER_PERSON",
                },
            ],
            "count": 1,
            "truncated": False,
        },
    ),
    tool(
        "budgets_list",
        "ok",
        data={
            "budgets": [
                {"budget_id": "b1", "currency": "AUD", "total_budget": "2500.00"}
            ],
            "count": 1,
            "truncated": False,
        },
    ),
]


def post(client_factory, backend_api, url, data, response, *, htmx=True):
    backend = FeatureBackend(backend_api, response)
    with client_factory(backend) as test_client:
        result = test_client.post(url, data=data, headers=HTMX_HEADERS if htmx else {})
    return result, backend


# --- trip page -------------------------------------------------------------


def test_trip_page_renders_both_panels_alongside_existing_sections(client) -> None:
    response = client.get(f"/trips/{TRIP_ID}")

    assert response.status_code == 200
    text = response.text
    assert '<label for="rag-question">Question</label>' in text
    assert 'maxlength="2000"' in text
    assert '<label for="mcp-country">Country (optional)</label>' in text
    assert 'placeholder="Australia"' in text
    assert 'hx-target="#rag-panel"' in text
    assert 'hx-target="#mcp-panel"' in text
    assert text.count('hx-disabled-elt="find button"') == 2
    assert 'id="rag-loading"' in text and 'id="mcp-loading"' in text
    # Existing Release 0 sections and the AI-Mode panel are still there.
    for heading in (
        "days-heading",
        "transport-heading",
        "activities-heading",
        "accommodation-heading",
        "ai-detail-heading",
    ):
        assert f'id="{heading}"' in text
    assert "Harbour Walk" in text
    # No result or error state until the user asks.
    assert 'id="rag-result-heading"' not in text
    assert 'id="mcp-result-heading"' not in text


# --- RAG -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("category", "label", "badge_class"),
    [
        ("high", "High confidence", 'class="badge "'),
        ("medium", "Medium confidence", "badge--warning"),
        ("low", "Low confidence — check the sources", "badge--danger"),
    ],
)
def test_rag_grounded_answer_shows_confidence_and_citations(
    client_factory,
    backend_api,
    category,
    label,
    badge_class,
) -> None:
    response, backend = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "What limits apply to itinerary items?"},
        data_response(200, rag_answer(confidence_category=category)),
    )

    assert response.status_code == 200
    text = response.text
    assert '<section id="rag-panel"' in text
    assert "<html" not in text and 'id="app-shell"' not in text
    assert text.count('id="rag-question"') == 1
    assert label in text and badge_class in text
    assert "Itinerary items must fall within the trip dates." in text
    assert "Student 1 backend" in text
    assert "Itinerary rules" in text
    assert "between start_date and end_date" in text
    assert "student-1/backend/README.md" in text
    assert "What limits apply to itinerary items?" in text
    assert 'id="rag-result-heading" data-autofocus' in text
    assert backend.bodies == [{"question": "What limits apply to itinerary items?"}]


def test_rag_insufficient_context_shows_no_answer_or_citations(
    client_factory,
    backend_api,
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "Best pizza on the moon?"},
        data_response(200, INSUFFICIENT),
    )

    assert response.status_code == 200
    assert "Not enough information to answer" in response.text
    assert "Insufficient context" in response.text
    assert "Something the model made up." not in response.text
    assert "Sources" not in response.text


@pytest.mark.parametrize(
    ("status", "code", "headline"),
    [
        (503, "RAG_DISABLED", "not enabled in this environment"),
        (503, "INDEX_NOT_READY", "index is not ready yet"),
        (503, "DEPENDENCY_UNAVAILABLE", "unavailable right now"),
        (504, "DEPENDENCY_TIMEOUT", "timed out"),
        (502, "BAD_GATEWAY", "could not read"),
    ],
)
def test_rag_failures_render_distinct_states(
    client_factory,
    backend_api,
    status,
    code,
    headline,
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "Keep me?"},
        error_response(status, code, "Upstream said no."),
    )

    assert response.status_code == status
    assert headline in response.text
    assert f"<code>{code}</code>" in response.text
    assert "Keep me?" in response.text
    assert 'id="rag-result-heading" data-autofocus' in response.text
    assert "Sources" not in response.text


def test_rag_disabled_is_informational_not_an_error_banner(
    client_factory,
    backend_api,
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "Anything"},
        error_response(503, "RAG_DISABLED", "RAG is disabled."),
    )

    assert 'class="banner banner--info"' in response.text


def test_rag_frontend_timeout_renders_timeout_state(
    client_factory, backend_api
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "Slow?"},
        httpx.ReadTimeout("slow model"),
    )

    assert response.status_code == 504
    assert "timed out" in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "no citations field"},
        # Claims grounding without any sources: malformed, never shown as fact.
        rag_answer(citations=[]),
        # Claims insufficient context yet carries an answer's citations.
        rag_answer(
            insufficient_context=True, confidence_category="insufficient_context"
        ),
    ],
)
def test_rag_malformed_response_is_an_error_not_an_answer(
    client_factory,
    backend_api,
    payload,
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "Malformed?"},
        data_response(200, payload),
    )

    assert response.status_code == 502
    assert "could not read" in response.text
    assert "Itinerary items must fall within the trip dates." not in response.text


def test_rag_validation_error_is_tied_to_the_question_field(
    client_factory,
    backend_api,
) -> None:
    response, backend = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": ""},
        error_response(
            422,
            "VALIDATION_ERROR",
            "One or more fields failed validation.",
            [{"field": "question", "issue": "String should have at least 1 character"}],
        ),
    )

    assert response.status_code == 422
    assert "Check the highlighted field" in response.text
    assert 'aria-invalid="true"' in response.text
    assert 'aria-describedby="rag-question-hint question-errors"' in response.text
    assert '<ul class="field-errors" id="question-errors">' in response.text
    assert backend.bodies == [{"question": ""}]


def test_rag_without_htmx_renders_the_full_trip_page(
    client_factory, backend_api
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        RAG_URL,
        {"question": "Full page?"},
        data_response(200, rag_answer()),
        htmx=False,
    )

    assert response.status_code == 200
    assert "<html" in response.text
    assert 'id="trip-detail-heading"' in response.text
    assert response.text.count('id="rag-panel"') == 1
    assert "Itinerary items must fall within the trip dates." in response.text


# --- MCP -------------------------------------------------------------------


def test_mcp_all_tools_ok_render_readable_summaries(
    client_factory, backend_api
) -> None:
    starting_items = set(backend_api.items)
    response, backend = post(
        client_factory,
        backend_api,
        MCP_URL,
        {"country": " Australia "},
        data_response(200, mcp_options(ALL_OK, "Australia")),
    )

    assert response.status_code == 200
    text = response.text
    assert '<section id="mcp-panel"' in text and "<html" not in text
    assert backend.bodies == [{"country": "Australia"}]
    assert "Options for Sydney, Australia" in text
    assert "5 succeeded · 0 failed · 0 skipped. Nothing was saved." in text
    assert "Sydney Getaway · Sydney · 2027-04-01 · 2027-04-03 · 2 traveller(s)" in text
    assert "Harbour Hotel · $210/night" in text
    assert "Bridge Climb · $300 per person" in text
    assert "More options are available than shown." in text
    assert "Harbour Ferries FERRY · Manly to Sydney · $9 per person" in text
    assert "b1 · AUD 2500.00" in text
    assert "<code>accommodations_search</code>" in text
    assert "country=Australia · city=Sydney · limit=5" in text
    assert "Some lookups failed" not in text
    # Read-only: no save controls and nothing persisted.
    assert "draft_payload" not in text
    assert "<form" in text and text.count("<form") == 1
    assert set(backend_api.items) == starting_items


def test_mcp_blank_country_is_sent_as_null(client_factory, backend_api) -> None:
    skipped = [
        tool(
            "accommodations_search",
            "skipped",
            reason="A country is needed; the trip destination names only a city.",
        ),
    ]
    response, backend = post(
        client_factory,
        backend_api,
        MCP_URL,
        {"country": "  "},
        data_response(200, mcp_options(skipped, None)),
    )

    assert backend.bodies == [{"country": None}]
    assert "Options for Sydney" in response.text
    assert "Options for Sydney," not in response.text
    assert "A country is needed" in response.text


def test_mcp_partial_failure_is_shown_per_tool(client_factory, backend_api) -> None:
    results = [
        ALL_OK[0],
        tool(
            "accommodations_search",
            "error",
            error={
                "code": "PROVIDER_UNAVAILABLE",
                "message": "Provider failed",
                "retryable": True,
            },
        ),
        tool(
            "activities_search",
            "skipped",
            reason="A country is needed; the trip destination names only a city.",
        ),
    ]
    response, _ = post(
        client_factory,
        backend_api,
        MCP_URL,
        {"country": ""},
        data_response(200, mcp_options(results, None)),
    )

    assert response.status_code == 200
    text = response.text
    assert "1 succeeded · 1 failed · 1 skipped" in text
    assert "Some lookups failed" in text
    assert "Provider failed" in text
    assert "<code>PROVIDER_UNAVAILABLE</code>, can be retried" in text
    assert '"badge badge--danger">Failed' in text
    assert '"badge badge--warning">Skipped' in text
    assert "A country is needed; the trip destination names only a city." in text
    assert "Sydney Getaway" in text


@pytest.mark.parametrize(
    ("status", "code", "headline"),
    [
        (503, "MCP_DISABLED", "not enabled in this environment"),
        (503, "DEPENDENCY_UNAVAILABLE", "unavailable right now"),
        (504, "DEPENDENCY_TIMEOUT", "timed out"),
        (404, "NOT_FOUND", "could not be found"),
        (422, "VALIDATION_ERROR", "Check the highlighted field"),
    ],
)
def test_mcp_failures_render_distinct_states(
    client_factory,
    backend_api,
    status,
    code,
    headline,
) -> None:
    response, _ = post(
        client_factory,
        backend_api,
        MCP_URL,
        {"country": "Australia"},
        error_response(
            status, code, "Upstream said no.", [{"field": "country", "issue": "bad"}]
        ),
    )

    assert response.status_code == status
    assert headline in response.text
    assert 'value="Australia"' in response.text
    assert 'id="mcp-result-heading"' in response.text
    assert "succeeded" not in response.text


def test_mcp_malformed_response_is_an_error(client_factory, backend_api) -> None:
    payload = mcp_options(ALL_OK, "Australia")
    payload["persisted"] = True
    response, _ = post(
        client_factory,
        backend_api,
        MCP_URL,
        {"country": "Australia"},
        data_response(200, payload),
    )

    assert response.status_code == 502
    assert "could not read" in response.text
    assert "Harbour Hotel" not in response.text


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (None, "No data returned."),
        ({"items": []}, "No matching options found."),
        ({"items": ["odd row"]}, "odd row"),
        ({"items": [{"id": "only-id"}]}, "only-id"),
        ({"weird": 1, "shape": 2}, "Returned fields: shape, weird"),
    ],
)
def test_mcp_summary_survives_unexpected_shapes(data, expected) -> None:
    from frontend_service.app import summarise_mcp_data

    assert expected in summarise_mcp_data(data)
