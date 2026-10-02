"""The ask box's RAG and MCP modes: the backend answers 200 with a `status`,
and these render each shape -- citations and confidence, an honest
insufficient context, and every tool call with the data it returned -- into
#ai-answer, leaving the results list alone."""

from __future__ import annotations

import pytest

KNOWLEDGE = "/accommodation/knowledge"
ASSISTANT = "/accommodation/assistant"
CITATION = {
    "source_id": "accommodation-pricing-and-costs",
    "path": "ai-services/rag-server/knowledge/accommodation/pricing-and-costs.md",
    "title": "Accommodation Pricing and Trip Costs",
    "section": "Accommodation costs: the cost of one stay",
    "chunk_id": "c1",
    "excerpt": "The cost of a stay is the price per night multiplied by",
}
ANSWERED = {
    "status": "answered",
    "request_id": "student2-rag-1",
    "answer": "Price per night times the nights.",
    "confidence_category": "high",
    "citations": [CITATION],
    "retrieval": {"requested_top_k": 5, "returned_chunks": 3, "maximum_score": 0.9},
    "run_id": "rag-run-1",
}
COMPLETE = {
    "status": "complete",
    "request_id": "student2-agent-1",
    "reply": "Harbour View Hotel is 320 a night.",
    "tools": [
        {
            "tool": "accommodations_search",
            "arguments": {"country": "Australia", "city": "Sydney"},
            "status": "success",
            "duration_ms": 40,
            "source": "student-2",
            "data": {
                "items": [
                    {
                        "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
                        "name": "Harbour View Hotel",
                        "type": "hotel",
                        "price_per_night": "320.00",
                        "availability_status": "available",
                        "location_details": {"country": "australia", "city": "sydney"},
                    }
                ],
                "count": 1,
                "truncated": False,
            },
            "error": None,
        }
    ],
}


MODES = {KNOWLEDGE: "rag", ASSISTANT: "mcp"}


def ask(client, path, question="How is a stay priced?"):
    """The ask box, posted in the mode that calls backend `path`."""
    response = client.post(
        "/accommodation/ai-search", content=f"query={question}&mode={MODES[path]}"
    )
    # Every RAG/MCP answer lands under the box, never over the results.
    assert response.headers["HX-Retarget"] == "#ai-answer"
    assert response.headers["HX-Reswap"] == "innerHTML"
    return response


def test_a_grounded_answer_shows_confidence_and_sources(client, backend):
    backend.answers[KNOWLEDGE] = ANSWERED
    html = ask(client, KNOWLEDGE).text
    assert "High confidence" in html
    assert "Price per night times the nights." in html
    assert "Accommodation Pricing and Trip Costs" in html
    assert "pricing-and-costs.md" in html
    _, body, timeout = backend.asked[0]
    assert body == {"question": "How is a stay priced?"}
    # A model is behind it: the AI timeout, not the page's ordinary 5s.
    assert timeout == client.app.state.settings.ai_timeout


def test_insufficient_context_shows_no_answer(client, backend):
    backend.answers[KNOWLEDGE] = {
        "status": "insufficient_context",
        "request_id": "r",
        "answer": "There is not enough indexed context to answer this question.",
        "confidence_category": "insufficient_context",
        "citations": [],
    }
    html = ask(client, KNOWLEDGE).text
    assert "Insufficient context" in html
    assert "Sources" not in html


@pytest.mark.parametrize("path", [KNOWLEDGE, ASSISTANT])
def test_a_disabled_box_says_so(client, backend, path):
    backend.answers[path] = {
        "status": "disabled",
        "request_id": "r",
        "error": "switched off here",
        "tools": [],
    }
    assert "switched off here" in ask(client, path).text


def test_tool_calls_and_their_data_are_shown(client, backend):
    backend.answers[ASSISTANT] = COMPLETE
    html = ask(client, ASSISTANT, "Stays in Sydney?").text
    assert "Harbour View Hotel is 320 a night." in html
    assert "Tools used · 1 call" in html
    assert "accommodations_search" in html
    # A readable table of the tool's rows, each linking to its modal...
    table = html.split("<table")[1].split("</table>")[0]
    assert "Harbour View Hotel" in table
    assert "?accommodation=3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11" in table
    assert "320.00" in table
    assert "Sydney, Australia" in table
    # ...and the raw tool result under it, as evidence the tool returned it.
    raw = html.split("Raw tool result")[1]
    assert '"truncated": false' in raw


def tool_answer(tool, data):
    call = dict(COMPLETE["tools"][0], tool=tool, arguments={}, data=data)
    return {**COMPLETE, "tools": [call]}


def test_a_single_listing_is_shown_as_its_details(client, backend):
    backend.answers[ASSISTANT] = tool_answer(
        "accommodations_get",
        {
            "id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
            "name": "Harbour View Hotel",
            "type": "hotel",
            "price_per_night": "320.00",
            "rating": 4.6,
            "amenities": ["wifi", "pool"],
            "availability_status": "available",
            "location_details": {"country": "australia", "city": "sydney"},
            "room_details": {"room_count": 1, "bed_count": 1, "bed_types": ["king"]},
        },
    )
    html = ask(client, ASSISTANT).text
    assert "wifi, pool" in html
    assert "1 rooms, 1 beds (king)" in html
    assert "Raw tool result" in html


def test_committed_costs_are_shown_with_their_total(client, backend):
    backend.answers[ASSISTANT] = tool_answer(
        "accommodations_committed_costs",
        {
            "committed_cost_total": "960.00",
            "currency": "AUD",
            "items": [
                {
                    "item_id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
                    "description": "Harbour View Hotel",
                    "status": "planned",
                    "amount": "960.00",
                    "currency": "AUD",
                }
            ],
        },
    )
    html = ask(client, ASSISTANT).text
    assert "Committed total" in html
    assert "960.00 AUD" in html


def test_another_features_tool_gets_the_raw_result_only(client, backend):
    backend.answers[ASSISTANT] = tool_answer("budgets_list", {"items": []})
    html = ask(client, ASSISTANT).text
    assert "<table" not in html
    assert "Raw tool result" in html


def test_a_failed_tool_is_shown_as_failed(client, backend):
    failed = dict(
        COMPLETE["tools"][0], status="error", data=None, error="VALIDATION_ERROR bad id"
    )
    backend.answers[ASSISTANT] = {
        "status": "error",
        "request_id": "r",
        "error": "model gave up",
        "tools": [failed],
    }
    html = ask(client, ASSISTANT).text
    assert "model gave up" in html
    assert "Tool failed: VALIDATION_ERROR bad id" in html


@pytest.mark.parametrize("path", [KNOWLEDGE, ASSISTANT])
def test_a_blank_question_never_reaches_the_backend(client, backend, path):
    assert "Type a question." in ask(client, path, "  ").text
    assert backend.asked == []


def test_the_ask_box_offers_three_modes_each_with_its_description(client):
    html = client.get("/").text
    assert 'name="mode" value="search" checked' in html
    assert 'name="mode" value="rag"' in html
    assert 'name="mode" value="mcp"' in html
    for mode in ("search", "rag", "mcp"):
        assert f"ask__desc--{mode}" in html
    assert "always list their sources" in html
    assert "shows each tool call" in html


def test_a_rag_answer_reports_how_much_context_it_used(client, backend):
    backend.answers[KNOWLEDGE] = ANSWERED
    html = ask(client, KNOWLEDGE).text
    assert "AI mode · knowledge base" in html
    assert "3 of 5 chunks used" in html


def test_the_default_mode_is_still_the_filter_search(client, backend):
    response = client.post(
        "/accommodation/ai-search", content="query=japan&mode=search"
    )
    assert "HX-Retarget" not in response.headers
    assert backend.ai_question == "japan"
    assert backend.asked == []
