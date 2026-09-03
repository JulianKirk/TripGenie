from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings

from .conftest import (
    BUDGET_ID,
    EXPENSE_ID,
    database_handler,
    provider_handler,
    trips_handler,
)

BUDGETS = "/api/budgets"
EXPENSES = "/api/expenses"


def test_trip_directory_is_read_from_student_1(client: TestClient) -> None:
    response = client.get("/api/trips")

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": "trip_chunk3",
            "name": "Integration Trip",
            "destination": "Sydney",
            "start_date": "2026-09-01",
            "end_date": "2026-09-10",
            "status": "planned",
        }
    ]


def test_budget_crud_is_forwarded(client: TestClient) -> None:
    created = client.post(
        BUDGETS,
        json={"trip_id": "trip_chunk3", "currency": "AUD", "total_budget": "1000.00"},
    )
    assert created.status_code == 201
    assert created.json()["data"]["total_budget"] == "1000.00"
    assert client.get(f"{BUDGETS}/{BUDGET_ID}").status_code == 200
    assert (
        client.patch(f"{BUDGETS}/{BUDGET_ID}", json={"total_budget": "1200.00"}).json()[
            "data"
        ]["total_budget"]
        == "1200.00"
    )
    assert client.delete(f"{BUDGETS}/{BUDGET_ID}").json()["data"]["deleted"] is True


def test_database_error_envelope_is_preserved(client: TestClient) -> None:
    response = client.post(
        BUDGETS,
        json={
            "trip_id": "trip_duplicate",
            "currency": "AUD",
            "total_budget": "1000.00",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_expense_crud_and_filters_are_forwarded(client: TestClient) -> None:
    created = client.post(
        EXPENSES,
        json={
            "trip_id": "trip_chunk3",
            "category": "food",
            "description": "Dinner",
            "amount": "100.10",
            "currency": "AUD",
            "date": "2026-09-02",
        },
    )
    assert created.status_code == 201
    response = client.get(
        EXPENSES,
        params={
            "trip_id": "trip_chunk3",
            "category": "food",
            "date_from": "2026-09-01",
            "date_to": "2026-09-10",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["expense_id"] == EXPENSE_ID
    assert (
        client.patch(f"{EXPENSES}/{EXPENSE_ID}", json={"amount": "110.00"}).json()[
            "data"
        ]["amount"]
        == "110.00"
    )
    assert client.delete(f"{EXPENSES}/{EXPENSE_ID}").status_code == 200


def test_expense_filter_query_reaches_database(settings: Settings) -> None:
    captured: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/expenses":
            captured.update(request.url.params)
        return database_handler(request)

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(capture),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(provider_handler),
    )
    with TestClient(app) as client:
        client.get(
            EXPENSES,
            params={
                "trip_id": "trip_chunk3",
                "category": "food",
                "date_from": "2026-09-01",
                "date_to": "2026-09-10",
            },
        )

    assert captured == {
        "trip_id": "trip_chunk3",
        "category": "food",
        "date_from": "2026-09-01",
        "date_to": "2026-09-10",
    }


def test_missing_trip_blocks_writes(client: TestClient) -> None:
    response = client.post(
        BUDGETS,
        json={"trip_id": "trip_missing", "currency": "AUD", "total_budget": "100.00"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "trip_id"


def test_unavailable_trip_lookup_does_not_block_owned_crud(client: TestClient) -> None:
    response = client.post(
        BUDGETS,
        json={"trip_id": "trip_offline", "currency": "AUD", "total_budget": "100.00"},
    )

    assert response.status_code == 201


def test_expense_date_is_validated_when_trip_is_available(client: TestClient) -> None:
    response = client.post(
        EXPENSES,
        json={
            "trip_id": "trip_chunk3",
            "category": "food",
            "description": "Late dinner",
            "amount": "30.00",
            "currency": "AUD",
            "date": "2026-09-20",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "date"


def test_trip_and_date_changes_are_validated_on_update(client: TestClient) -> None:
    budget = client.patch(f"{BUDGETS}/{BUDGET_ID}", json={"trip_id": "trip_missing"})
    expense = client.patch(f"{EXPENSES}/{EXPENSE_ID}", json={"date": "2026-09-20"})

    assert budget.status_code == 422
    assert expense.status_code == 422


def test_summary_matches_hand_calculation_and_reports_partial_providers(
    client: TestClient,
) -> None:
    response = client.get(f"{BUDGETS}/{BUDGET_ID}/summary")

    assert response.status_code == 200, response.text
    summary = response.json()["data"]
    assert summary["actual_spending"] == "100.10"
    assert summary["committed_costs"] == "200.20"
    assert summary["remaining_budget"] == "699.70"
    assert summary["providers"]["transport"]["status"] == "available"
    assert summary["providers"]["transport"]["items"] == [
        {
            "item_id": "booking_ferry",
            "description": "Harbour Ferry: Sydney to Manly",
            "status": "pending",
            "amount": "200.20",
            "currency": "AUD",
        }
    ]
    assert summary["providers"]["accommodation"]["status"] == "unavailable"
    assert summary["committed_costs_complete"] is False


def test_current_transport_payload_without_currency_is_invalid(
    settings: Settings,
) -> None:
    def current_student3(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"estimated_cost_total": 200.20}})

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(database_handler),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(current_student3),
    )
    with TestClient(app) as client:
        summary = client.get(f"{BUDGETS}/{BUDGET_ID}/summary").json()["data"]

    assert summary["providers"]["transport"]["status"] == "invalid_response"
    assert summary["committed_costs"] == "0.00"


def test_transport_currency_mismatch_is_not_aggregated(settings: Settings) -> None:
    def usd_transport(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"estimated_cost_total": "200.20", "currency": "USD"}},
        )

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(database_handler),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(usd_transport),
    )
    with TestClient(app) as client:
        summary = client.get(f"{BUDGETS}/{BUDGET_ID}/summary").json()["data"]

    assert summary["providers"]["transport"]["status"] == "unavailable"
    assert summary["providers"]["transport"]["currency"] == "USD"
    assert summary["committed_costs"] == "0.00"


def test_provider_failure_does_not_hide_local_summary(settings: Settings) -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(database_handler),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(offline),
    )
    with TestClient(app) as client:
        response = client.get(f"{BUDGETS}/{BUDGET_ID}/summary")

    assert response.status_code == 200
    assert response.json()["data"]["actual_spending"] == "100.10"
    assert response.json()["data"]["providers"]["transport"]["status"] == "unavailable"


def test_database_failure_degrades_health_and_blocks_crud(settings: Settings) -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(offline),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(provider_handler),
    )
    with TestClient(app) as client:
        assert client.get("/health").json()["data"]["status"] == "degraded"
        assert client.get("/ready").status_code == 503
        response = client.get(BUDGETS)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_malformed_database_response_is_a_bad_gateway(settings: Settings) -> None:
    malformed = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"unexpected": []})
    )
    app = create_app(
        settings,
        database_transport=malformed,
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(provider_handler),
    )
    with TestClient(app) as client:
        response = client.get(BUDGETS)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INVALID_DEPENDENCY_RESPONSE"
