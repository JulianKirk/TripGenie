from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings

BUDGET_ID = "11111111-1111-4111-8111-111111111111"
EXPENSE_ID = "22222222-2222-4222-8222-222222222222"
TIMESTAMP = "2026-09-02T00:00:00Z"

BUDGET = {
    "budget_id": BUDGET_ID,
    "trip_id": "trip_chunk3",
    "currency": "AUD",
    "total_budget": "1000.00",
    "accommodation_budget": "0.00",
    "transport_budget": "0.00",
    "activities_budget": "0.00",
    "food_budget": "0.00",
    "other_budget": "0.00",
    "created_at": TIMESTAMP,
    "updated_at": TIMESTAMP,
}

EXPENSE = {
    "expense_id": EXPENSE_ID,
    "trip_id": "trip_chunk3",
    "category": "food",
    "description": "Dinner",
    "amount": "100.10",
    "currency": "AUD",
    "date": "2026-09-02",
    "payment_method": None,
    "notes": None,
    "created_at": TIMESTAMP,
    "updated_at": TIMESTAMP,
}


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content) if request.content else {}


def database_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/ready":
        return httpx.Response(200, json={"data": {"status": "ready"}})

    if path == "/internal/budgets":
        if request.method == "GET":
            return httpx.Response(200, json={"data": [BUDGET]})
        payload = _body(request)
        if payload["trip_id"] == "trip_duplicate":
            return httpx.Response(
                409,
                json={
                    "error": {
                        "code": "CONFLICT",
                        "message": "A budget already exists for this trip.",
                        "details": [{"field": "trip_id", "issue": "already exists"}],
                    }
                },
            )
        return httpx.Response(
            201,
            json={"data": BUDGET | payload | {"budget_id": BUDGET_ID}},
        )

    if path == f"/internal/budgets/{BUDGET_ID}":
        if request.method == "GET":
            return httpx.Response(200, json={"data": BUDGET})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": BUDGET | _body(request)})
        return httpx.Response(200, json={"data": {"id": BUDGET_ID, "deleted": True}})

    if path == "/internal/expenses":
        if request.method == "GET":
            return httpx.Response(200, json={"data": [EXPENSE]})
        payload = _body(request)
        return httpx.Response(
            201,
            json={"data": EXPENSE | payload | {"expense_id": EXPENSE_ID}},
        )

    if path == f"/internal/expenses/{EXPENSE_ID}":
        if request.method == "GET":
            return httpx.Response(200, json={"data": EXPENSE})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": EXPENSE | _body(request)})
        return httpx.Response(200, json={"data": {"id": EXPENSE_ID, "deleted": True}})

    return httpx.Response(404)


def trips_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/trips":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "trip_chunk3",
                        "name": "Integration Trip",
                        "destination": "Sydney",
                        "start_date": "2026-09-01",
                        "end_date": "2026-09-10",
                        "status": "planned",
                    }
                ]
            },
        )
    trip_id = request.url.path.rsplit("/", 1)[-1]
    if trip_id == "trip_missing":
        return httpx.Response(404)
    if trip_id == "trip_offline":
        raise httpx.ConnectError("offline", request=request)
    return httpx.Response(
        200,
        json={
            "data": {
                "id": trip_id,
                "start_date": "2026-09-01",
                "end_date": "2026-09-10",
            }
        },
    )


def provider_handler(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "estimated_cost_total": "200.20",
                "currency": "AUD",
                "planned": [
                    {
                        "entry": {
                            "id": "booking_ferry",
                            "booking_status": "pending",
                            "estimated_cost": "200.20",
                        },
                        "option": {
                            "provider": "Harbour Ferry",
                            "origin": "Sydney",
                            "destination": "Manly",
                        },
                    }
                ],
            }
        },
    )


def accommodation_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/accommodation/trips/trip_chunk3/committed-costs"
    return httpx.Response(
        200,
        json={
            "committed_cost_total": "379.00",
            "currency": "AUD",
            "items": [
                {
                    "item_id": "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11",
                    "description": "Harbour Hotel",
                    "status": "planned",
                    "amount": "379.00",
                    "currency": "AUD",
                }
            ],
        },
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_api_base_url="http://database.test",
        trips_api_base_url="http://trips.test",
        transport_api_base_url="http://transport.test",
        accommodation_api_base_url="http://accommodation.test",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(
        settings,
        database_transport=httpx.MockTransport(database_handler),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(provider_handler),
        accommodation_transport=httpx.MockTransport(accommodation_handler),
    )
    with TestClient(app) as test_client:
        yield test_client
