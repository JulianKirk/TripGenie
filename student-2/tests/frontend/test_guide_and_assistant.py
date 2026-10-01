"""The guide (RAG) and assistant (MCP) boxes: the backend answers 200 with a
`status`, and these render each shape -- citations and confidence, an honest
insufficient context, and every tool call with the data it returned."""

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
            "data": {"items": [{"name": "Harbour View Hotel"}], "count": 1},
            "error": None,
        }
    ],
}


def ask(client, path, question="How is a stay priced?"):
    return client.post(path, content=f"question={question}")


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
    assert "Returned data" in html
    assert "Harbour View Hotel" in html.split("Returned data")[1]


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


def test_the_page_has_both_boxes(client):
    html = client.get("/").text
    assert 'for="guide-question"' in html
    assert 'for="assistant-question"' in html
