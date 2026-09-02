from __future__ import annotations

from typing import Any

import httpx
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
    "providers": {"transport": {"status": "unavailable"}},
}


def response(
    request: httpx.Request, data: Any, status_code: int = 200
) -> httpx.Response:
    return httpx.Response(status_code, request=request, json=data)


def backend(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/ready":
        return response(request, {"data": {"status": "ready"}})
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
    assert "trip-7" in page.text
    assert "AUD 2000.00" in page.text


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
    assert "Some provider costs are unavailable" in page.text
    assert "Planned allocations" in page.text
    assert "AUD 800.00" in page.text
    assert "Dinner" in page.text
    expense_request = next(
        item for item in requests if item.url.path == "/api/v1/expenses"
    )
    assert expense_request.url.params["trip_id"] == "trip-7"
    assert expense_request.url.params["category"] == "food"
    assert expense_request.url.params["date_from"] == "2026-09-01"


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
    assert "String should match pattern" in page.text


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