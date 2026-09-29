from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student5_frontend_service.app import create_app

BUDGET_ID = "11111111-1111-1111-1111-111111111111"
EXPENSE_ID = "22222222-2222-2222-2222-222222222222"
BUDGET = {
    "budget_id": BUDGET_ID,
    "trip_id": "trip-7",
    "currency": "AUD",
    "total_budget": "2000.00",
    "accommodation_budget": "800.00",
    "transport_budget": "400.00",
    "activities_budget": "200.00",
    "food_budget": "300.00",
    "other_budget": "100.00",
}
EXPENSE = {
    "expense_id": EXPENSE_ID,
    "trip_id": "trip-7",
    "category": "food",
    "description": "Dinner",
    "amount": "75.00",
    "currency": "AUD",
    "date": "2026-09-02",
    "payment_method": "Card",
    "notes": None,
}
SUMMARY = {
    "currency": "AUD",
    "total_budget": "2000.00",
    "actual_spending": "75.00",
    "actual_spending_complete": True,
    "committed_costs": "300.00",
    "committed_costs_complete": False,
    "remaining_budget": "1625.00",
    "remaining_budget_complete": False,
    "providers": {
        "transport": {
            "status": "available",
            "subtotal": "300.00",
            "currency": "AUD",
            "items": [
                {
                    "description": "Harbour Ferry: Sydney to Manly",
                    "status": "pending",
                    "amount": "300.00",
                    "currency": "AUD",
                }
            ],
        },
        "accommodation": {
            "status": "unavailable",
            "detail": "provider contract is not available",
            "items": [],
        },
    },
}
TRIP = {
    "id": "trip-7",
    "name": "Sydney Long Weekend",
    "destination": "Sydney",
    "start_date": "2026-10-02",
    "end_date": "2026-10-05",
    "status": "planned",
}


def response(
    request: httpx.Request, data: Any, status_code: int = 200
) -> httpx.Response:
    return httpx.Response(status_code, request=request, json=data)


def backend(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/ready":
        return response(request, {"data": {"status": "ready"}})
    if path == "/api/v1/trips":
        return response(request, {"data": [TRIP]})
    if path == "/api/v1/budgets" and request.method == "GET":
        return response(request, {"data": [BUDGET]})
    if path == "/api/v1/budgets" and request.method == "POST":
        return response(request, {"data": BUDGET}, 201)
    if path == f"/api/v1/budgets/{BUDGET_ID}/summary":
        return response(request, {"data": SUMMARY})
    if path == f"/api/v1/budgets/{BUDGET_ID}/ai-analysis":
        return response(
            request,
            {
                "data": {
                    "analysis": {
                        "overview": "Spending is within budget.",
                        "risks": ["Provider costs are incomplete."],
                        "recommendations": ["Keep a contingency reserve."],
                        "disclaimer": "Advisory only; review before acting.",
                    },
                    "run_id": "aimode_1234",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                }
            },
        )
    if path == f"/api/v1/budgets/{BUDGET_ID}":
        if request.method == "DELETE":
            return response(request, {"data": {"deleted": True}})
        return response(request, {"data": BUDGET})
    if path == "/api/v1/expenses" and request.method == "GET":
        return response(request, {"data": [EXPENSE]})
    if path == "/api/v1/expenses" and request.method == "POST":
        return response(request, {"data": EXPENSE}, 201)
    if path == f"/api/v1/expenses/{EXPENSE_ID}":
        if request.method == "DELETE":
            return response(request, {"data": {"deleted": True}})
        return response(request, {"data": EXPENSE})
    raise AssertionError(f"Unexpected backend request: {request.method} {request.url}")


def make_client(handler=backend) -> TestClient:
    return TestClient(create_app(backend_transport=httpx.MockTransport(handler)))


def test_health_readiness_and_budget_list() -> None:
    with make_client() as client:
        assert client.get("/health").json() == {
            "data": {"status": "healthy", "service": "student-5-frontend"}
        }
        assert client.get("/ready").status_code == 200
        page = client.get("/")

    assert "Budget &amp; Expense Management" in page.text
    assert 'href="http://localhost:8080/theme.css"' in page.text
    assert (
        '<a class="site-home" href="http://localhost:8080">Home</a>'
        in page.text
    )
    assert "Sydney Long Weekend" in page.text
    assert "Sydney &middot; 2026-10-02 to 2026-10-05" in page.text
    assert "AUD 2000.00" in page.text
    assert 'href="http://localhost:8080">Home</a>' in page.text
    assert 'aria-label="TripGenie modules"' not in page.text


def test_budget_form_uses_live_student_1_trip_directory() -> None:
    with make_client() as client:
        page = client.get("/budgets/new")

    assert '<option value="trip-7"' in page.text
    assert "Sydney Long Weekend &middot; Sydney" in page.text
    assert 'name="currency" type="text"' in page.text
    assert 'pattern="[A-Z]{3}" maxlength="3"' in page.text


def test_budget_card_css_contains_long_trip_ids() -> None:
    with make_client() as client:
        css = client.get("/static/css/styles.css")

    assert css.status_code == 200
    assert "minmax(280px, 1fr)" in css.text
    assert (
        ".budget-card h3 a { color: var(--ink); overflow-wrap: anywhere; }" in css.text
    )


def test_htmx_detail_filters_expenses_and_shows_incomplete_summary() -> None:
    requests: list[httpx.Request] = []

    def recording_backend(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return backend(request)

    with make_client(recording_backend) as client:
        page = client.get(
            f"/budgets/{BUDGET_ID}?category=food&date_from=2026-09-01",
            headers={"HX-Request": "true"},
        )

    assert page.text.lstrip().startswith('<main id="app-shell"')
    assert "<html" not in page.text
    assert "Committed *" in page.text
    assert "Provider costs not included" in page.text
    assert (
        "<strong>Accommodation</strong>: provider contract is not available"
        in page.text
    )
    assert "How remaining is calculated" in page.text
    assert "Harbour Ferry: Sydney to Manly" in page.text
    assert "AUD 2000.00 &minus; AUD 300.00 committed" in page.text
    assert "&minus; AUD 75.00 actual = <strong>AUD 1625.00</strong>" in page.text
    assert "Planned allocations" in page.text
    assert "Sydney Long Weekend" in page.text
    assert "AUD 800.00" in page.text
    assert "Dinner" in page.text
    expense_request = next(
        item for item in requests if item.url.path == "/api/v1/expenses"
    )
    assert expense_request.url.params["trip_id"] == "trip-7"
    assert expense_request.url.params["category"] == "food"
    assert expense_request.url.params["date_from"] == "2026-09-01"


def test_trip_directory_failure_preserves_owned_budget_views() -> None:
    def trips_offline(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/trips":
            return response(
                request,
                {
                    "error": {
                        "code": "DEPENDENCY_UNAVAILABLE",
                        "message": "The trips service is unavailable.",
                        "details": [],
                    }
                },
                503,
            )
        return backend(request)

    with make_client(trips_offline) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert "Live trip details are unavailable" in page.text
    assert "trip-7" in page.text
    assert "AUD 2000.00" in page.text


def test_budget_analysis_action_displays_structured_advice() -> None:
    with make_client() as client:
        detail = client.get(f"/budgets/{BUDGET_ID}")
        result = client.post(
            f"/budgets/{BUDGET_ID}/ai-analysis",
            data={"question": "Can I afford another activity?"},
            headers={"HX-Request": "true"},
        )

    assert "What would you like to understand?" in detail.text
    assert "Spending is within budget." in result.text
    assert "Keep a contingency reserve." in result.text
    assert "qwen2.5:0.5b via ollama" in result.text
    assert 'value="Can I afford another activity?"' not in result.text
    assert "Can I afford another activity?" in result.text


def test_budget_analysis_failure_keeps_question_and_shows_unavailable_state() -> None:
    def offline_ai(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ai-analysis"):
            return response(
                request,
                {
                    "error": {
                        "code": "DEPENDENCY_UNAVAILABLE",
                        "message": "The AI provider is unavailable.",
                        "details": [],
                    }
                },
                503,
            )
        return backend(request)

    with make_client(offline_ai) as client:
        result = client.post(
            f"/budgets/{BUDGET_ID}/ai-analysis",
            data={"question": "Where can I save?"},
        )

    assert "AI analysis is unavailable" in result.text
    assert "The AI provider is unavailable." in result.text
    assert "Where can I save?" in result.text
    assert "Budget and expense actions remain available." in result.text


def test_budget_validation_preserves_submitted_values() -> None:
    def invalid_backend(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/budgets" and request.method == "POST":
            return response(
                request,
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "One or more fields failed validation.",
                        "details": [
                            {
                                "field": "currency",
                                "issue": "String should match pattern",
                            }
                        ],
                    }
                },
                422,
            )
        return backend(request)

    form = {
        "trip_id": "trip-preserved",
        "currency": "aud",
        "total_budget": "100.00",
        "accommodation_budget": "0.00",
        "transport_budget": "0.00",
        "activities_budget": "0.00",
        "food_budget": "0.00",
        "other_budget": "0.00",
    }
    with make_client(invalid_backend) as client:
        page = client.post("/budgets", data=form)

    assert page.status_code == 200
    assert 'value="trip-preserved"' in page.text
    assert 'value="aud"' in page.text
    assert "Please correct the following:" in page.text
    assert "Currency must use three uppercase letters, for example AUD." in page.text
    assert "One or more fields failed validation." not in page.text


def test_expense_validation_identifies_each_invalid_field() -> None:
    def invalid_backend(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/expenses" and request.method == "POST":
            return response(
                request,
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "One or more fields failed validation.",
                        "details": [
                            {
                                "field": "amount",
                                "issue": "Input should be greater than 0",
                            },
                            {
                                "field": "date",
                                "issue": "Input should be a valid date or datetime",
                            },
                        ],
                    }
                },
                422,
            )
        return backend(request)

    form = {
        "trip_id": "trip-7",
        "category": "food",
        "description": "Dinner",
        "amount": "0",
        "currency": "AUD",
        "date": "not-a-date",
        "payment_method": "Card",
        "notes": "",
    }
    with make_client(invalid_backend) as client:
        page = client.post(f"/budgets/{BUDGET_ID}/expenses", data=form)

    assert page.status_code == 200
    assert 'value="0"' in page.text
    assert "Please correct the following:" in page.text
    assert "Amount must be greater than zero." in page.text
    assert "Enter a valid date." in page.text
    assert "One or more fields failed validation." not in page.text


def test_create_and_delete_routes_redirect_to_browser_views() -> None:
    expense_form = {
        "trip_id": "trip-7",
        "category": "food",
        "description": "Dinner",
        "amount": "75.00",
        "currency": "AUD",
        "date": "2026-09-02",
        "payment_method": "Card",
        "notes": "",
    }
    with make_client() as client:
        created = client.post(
            f"/budgets/{BUDGET_ID}/expenses",
            data=expense_form,
            follow_redirects=False,
        )
        confirmation = client.get(
            f"/expenses/{EXPENSE_ID}/delete?budget_id={BUDGET_ID}"
        )
        deleted = client.post(
            f"/expenses/{EXPENSE_ID}/delete?budget_id={BUDGET_ID}",
            follow_redirects=False,
        )

    assert created.headers["location"] == f"/budgets/{BUDGET_ID}"
    assert "Delete permanently" in confirmation.text
    assert deleted.headers["location"] == f"/budgets/{BUDGET_ID}"


CITATION = {
    "source_id": "student-5-budget-rules",
    "path": "student-5/docs/budget-rules.md",
    "title": "Student 5 Budget and Expense Rules",
    "section": "Remaining budget",
    "chunk_id": "student-5-budget-rules:2:ab12cd",
    "excerpt": "remaining_budget = total_budget - committed_costs - actual_spending",
}
RAG_ANSWER = {
    "answer": "Remaining budget is total minus committed and actual spending.",
    "confidence_category": "medium",
    "insufficient_context": False,
    "citations": [CITATION],
    "retrieval": {"requested_top_k": 5, "returned_chunks": 1, "maximum_score": 0.6},
    "run_id": "rag_01",
    "correlation_id": "student5-rag-0123456789ab",
}
MCP_SUMMARY = {
    "action": "budget-summary",
    "tool": "budgets_get_summary",
    "correlation_id": "student5-mcp-0123456789ab",
    "duration_ms": 412,
    "result": SUMMARY
    | {
        "budget_id": BUDGET_ID,
        "trip_id": "trip-7",
        "unconverted_expense_count": 0,
        "category_totals": {"food": "75.00"},
    },
}


def error_body(code: str, message: str, details=None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}


def with_route(path: str, data: Any, status_code: int = 200):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == path and request.method == "POST":
            captured.append(request)
            return response(request, data, status_code)
        return backend(request)

    return handler, captured


def test_budget_list_includes_accessible_rag_panel() -> None:
    with make_client() as client:
        page = client.get("/")

    assert 'id="rag-assistant"' in page.text
    assert 'aria-live="polite"' in page.text
    assert '<form method="post" action="/rag" hx-post="/rag"' in page.text
    assert "<span>Your question</span><textarea" in page.text
    assert 'maxlength="500"' in page.text


def test_rag_grounded_answer_shows_confidence_and_citations() -> None:
    handler, captured = with_route("/api/v1/rag/query", {"data": RAG_ANSWER})
    with make_client(handler) as client:
        result = client.post(
            "/rag",
            data={"question": " How is remaining calculated? "},
            headers={"HX-Request": "true"},
        )

    assert result.text.lstrip().startswith('<div id="rag-assistant"')
    assert "Confidence: Medium" in result.text
    assert RAG_ANSWER["answer"] in result.text
    assert "Student 5 Budget and Expense Rules</strong> &middot; Remaining budget" in (
        result.text
    )
    assert "student-5/docs/budget-rules.md" in result.text
    assert "student5-rag-0123456789ab" in result.text
    assert json.loads(captured[0].read()) == {
        "question": "How is remaining calculated?"
    }


def test_rag_insufficient_context_shows_fixed_message_without_citations() -> None:
    insufficient = RAG_ANSWER | {
        "answer": "There is not enough indexed context to answer this question.",
        "confidence_category": "insufficient_context",
        "insufficient_context": True,
        "citations": [],
    }
    handler, _ = with_route("/api/v1/rag/query", {"data": insufficient})
    with make_client(handler) as client:
        result = client.post(
            "/rag", data={"question": "Who won?"}, headers={"HX-Request": "true"}
        )

    assert "not enough indexed context" in result.text
    assert "Confidence: Insufficient context" in result.text
    assert "<h3>Sources</h3>" not in result.text


def test_rag_without_javascript_renders_full_page() -> None:
    handler, _ = with_route("/api/v1/rag/query", {"data": RAG_ANSWER})
    with make_client(handler) as client:
        result = client.post("/rag", data={"question": "How is remaining calculated?"})

    assert "<html" in result.text
    assert "Sydney Long Weekend" in result.text
    assert "Confidence: Medium" in result.text


@pytest.mark.parametrize(
    ("status_code", "code", "message"),
    [
        (503, "RAG_DISABLED", "(RAG) is disabled in this environment."),
        (503, "INDEX_NOT_READY", "The knowledge index is not ready yet."),
        (503, "DEPENDENCY_UNAVAILABLE", "knowledge assistant is currently unavailable"),
        (504, "DEPENDENCY_TIMEOUT", "took too long to answer"),
        (502, "INVALID_DEPENDENCY_RESPONSE", "gave an unusable reply"),
        (422, "VALIDATION_ERROR", "Enter a question between 1 and 500 characters."),
    ],
)
def test_rag_failure_states_are_distinct_and_keep_question(
    status_code: int, code: str, message: str
) -> None:
    handler, _ = with_route(
        "/api/v1/rag/query", error_body(code, "raw backend text"), status_code
    )
    with make_client(handler) as client:
        result = client.post(
            "/rag",
            data={"question": "Keep this question"},
            headers={"HX-Request": "true"},
        )

    assert message in result.text
    assert "Keep this question</textarea>" in result.text
    assert "Budget and expense actions remain available." in result.text


def test_rag_output_is_escaped() -> None:
    hostile = RAG_ANSWER | {
        "answer": "<script>alert(1)</script>",
        "citations": [CITATION | {"excerpt": "<img src=x onerror=alert(1)>"}],
    }
    handler, _ = with_route("/api/v1/rag/query", {"data": hostile})
    with make_client(handler) as client:
        result = client.post(
            "/rag",
            data={"question": "<b>q</b>"},
            headers={"HX-Request": "true"},
        )

    assert "<script>" not in result.text
    assert "<img" not in result.text
    assert "<b>q</b>" not in result.text
    assert "&lt;script&gt;" in result.text


def test_budget_detail_includes_mcp_actions() -> None:
    with make_client() as client:
        page = client.get(f"/budgets/{BUDGET_ID}")

    assert 'id="mcp-tools"' in page.text
    assert f'action="/budgets/{BUDGET_ID}/mcp/budget-summary"' in page.text
    assert f'hx-post="/budgets/{BUDGET_ID}/mcp/expenses"' in page.text


def test_mcp_summary_result_is_readable_and_structured() -> None:
    handler, _ = with_route(
        f"/api/v1/budgets/{BUDGET_ID}/mcp/budget-summary", {"data": MCP_SUMMARY}
    )
    with make_client(handler) as client:
        result = client.post(
            f"/budgets/{BUDGET_ID}/mcp/budget-summary",
            headers={"HX-Request": "true"},
        )

    assert result.text.lstrip().startswith('<div id="mcp-tools"')
    assert "<code>budgets_get_summary</code>" in result.text
    assert "student5-mcp-0123456789ab" in result.text
    assert "412 ms" in result.text
    assert "AUD 1625.00" in result.text
    assert "<strong>Accommodation</strong>: unavailable" in result.text
    assert "<strong>Transport</strong>: available (AUD 300.00)" in result.text
    assert "Structured tool result" in result.text


def test_mcp_expenses_result_renders_table() -> None:
    data = {
        "action": "expenses",
        "tool": "expenses_list",
        "correlation_id": "student5-mcp-0123456789ab",
        "duration_ms": 9,
        "result": {"expenses": [EXPENSE], "count": 1, "truncated": True},
    }
    handler, _ = with_route(f"/api/v1/budgets/{BUDGET_ID}/mcp/expenses", {"data": data})
    with make_client(handler) as client:
        result = client.post(
            f"/budgets/{BUDGET_ID}/mcp/expenses", headers={"HX-Request": "true"}
        )

    assert "<td>Dinner</td>" in result.text
    assert "more exist than the tool limit" in result.text


def test_mcp_without_javascript_renders_full_detail_page() -> None:
    handler, _ = with_route(
        f"/api/v1/budgets/{BUDGET_ID}/mcp/budget-summary", {"data": MCP_SUMMARY}
    )
    with make_client(handler) as client:
        result = client.post(f"/budgets/{BUDGET_ID}/mcp/budget-summary")

    assert "<html" in result.text
    assert "Planned allocations" in result.text
    assert "<code>budgets_get_summary</code>" in result.text


@pytest.mark.parametrize(
    ("status_code", "code", "details", "message"),
    [
        (503, "MCP_DISABLED", [], "MCP tools are disabled in this environment."),
        (503, "DEPENDENCY_UNAVAILABLE", [], "shared MCP server is currently"),
        (
            503,
            "DEPENDENCY_UNAVAILABLE",
            [{"field": "mcp", "issue": "tool not registered"}],
            "not registered on the shared MCP server",
        ),
        (504, "DEPENDENCY_TIMEOUT", [], "took too long to respond"),
        (502, "MCP_TOOL_ERROR", [], "reported an error: raw backend text"),
        (502, "INVALID_DEPENDENCY_RESPONSE", [], "returned an unusable result"),
        (404, "NOT_FOUND", [], "raw backend text"),
    ],
)
def test_mcp_failure_states_are_distinct(
    status_code: int, code: str, details: list, message: str
) -> None:
    handler, _ = with_route(
        f"/api/v1/budgets/{BUDGET_ID}/mcp/budget-summary",
        error_body(code, "raw backend text", details),
        status_code,
    )
    with make_client(handler) as client:
        result = client.post(
            f"/budgets/{BUDGET_ID}/mcp/budget-summary",
            headers={"HX-Request": "true"},
        )

    assert message in result.text
    assert "Budget and expense actions remain available." in result.text


def test_mcp_structured_result_is_escaped() -> None:
    hostile = MCP_SUMMARY | {
        "result": MCP_SUMMARY["result"] | {"trip_id": "<script>x</script>"}
    }
    handler, _ = with_route(
        f"/api/v1/budgets/{BUDGET_ID}/mcp/budget-summary", {"data": hostile}
    )
    with make_client(handler) as client:
        result = client.post(
            f"/budgets/{BUDGET_ID}/mcp/budget-summary",
            headers={"HX-Request": "true"},
        )

    assert "<script>" not in result.text
