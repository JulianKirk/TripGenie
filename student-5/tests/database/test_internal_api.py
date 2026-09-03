from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from student5_database_service.app import create_app
from student5_database_service.config import Settings
from student5_database_service.seed_data import SEED_BUDGETS, SEED_EXPENSES

BUDGETS = "/internal/budgets"
EXPENSES = "/internal/expenses"
TRIP_WINDOWS = {
    "trip_2026_sydney_long_weekend": ("2026-10-02", "2026-10-05"),
    "trip_2026_melbourne_food_trail": ("2026-11-12", "2026-11-16"),
    "trip_2027_tokyo_spring_visit": ("2027-03-28", "2027-04-04"),
    "trip_2026_gold_coast_family_break": ("2026-12-20", "2026-12-27"),
    "trip_2027_queenstown_ski_escape": ("2027-07-10", "2027-07-16"),
    "trip_2026_singapore_stopover": ("2026-09-01", "2026-09-03"),
    "trip_2026_perth_workcation": ("2026-08-18", "2026-08-24"),
    "trip_2026_hobart_weekend_escape": ("2026-06-11", "2026-06-14"),
    "trip_2027_brisbane_city_break": ("2027-01-21", "2027-01-24"),
    "trip_2027_adelaide_festival_week": ("2027-02-26", "2027-03-03"),
}

NEW_BUDGET: dict[str, Any] = {
    "trip_id": "trip_chunk2",
    "currency": "AUD",
    "total_budget": "2000.00",
    "accommodation_budget": "800.00",
    "transport_budget": "400.00",
    "activities_budget": "200.00",
    "food_budget": "300.00",
    "other_budget": "100.00",
}

NEW_EXPENSE: dict[str, Any] = {
    "trip_id": "trip_chunk2",
    "category": "food",
    "description": "Dinner",
    "amount": "45.50",
    "currency": "AUD",
    "date": "2026-09-02",
    "payment_method": "card",
    "notes": "Team meal",
}


def _data(response) -> Any:
    return response.json()["data"]


def _create_budget(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(BUDGETS, json=NEW_BUDGET | overrides)
    assert response.status_code == 201, response.text
    return _data(response)


def _create_expense(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(EXPENSES, json=NEW_EXPENSE | overrides)
    assert response.status_code == 201, response.text
    return _data(response)


def test_budget_crud_lifecycle(client: TestClient) -> None:
    created = _create_budget(client)
    UUID(created["budget_id"])
    assert created["total_budget"] == "2000.00"
    assert _data(client.get(BUDGETS, params={"trip_id": "trip_chunk2"})) == [created]

    response = client.patch(
        f"{BUDGETS}/{created['budget_id']}",
        json={"total_budget": "2100.00", "food_budget": "400.00"},
    )
    assert response.status_code == 200, response.text
    assert _data(response)["food_budget"] == "400.00"

    response = client.delete(f"{BUDGETS}/{created['budget_id']}")
    assert response.status_code == 200
    assert _data(response)["deleted"] is True
    assert client.get(f"{BUDGETS}/{created['budget_id']}").status_code == 404


def test_budget_trip_must_be_unique(client: TestClient) -> None:
    _create_budget(client)
    response = client.post(BUDGETS, json=NEW_BUDGET)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_budget_rejects_invalid_and_empty_updates(client: TestClient) -> None:
    created = _create_budget(client)

    assert client.patch(f"{BUDGETS}/{created['budget_id']}", json={}).status_code == 422
    response = client.patch(
        f"{BUDGETS}/{created['budget_id']}",
        json={"total_budget": "100.00"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_expense_crud_lifecycle(client: TestClient) -> None:
    created = _create_expense(client)
    UUID(created["expense_id"])
    assert created["amount"] == "45.50"

    response = client.patch(
        f"{EXPENSES}/{created['expense_id']}",
        json={"amount": "50.25", "notes": None},
    )
    assert response.status_code == 200, response.text
    assert _data(response)["amount"] == "50.25"
    assert _data(response)["notes"] is None

    response = client.delete(f"{EXPENSES}/{created['expense_id']}")
    assert response.status_code == 200
    assert client.get(f"{EXPENSES}/{created['expense_id']}").status_code == 404


def test_expense_filters_can_be_combined(client: TestClient) -> None:
    expected = _create_expense(client)
    _create_expense(
        client,
        trip_id="trip_other",
        category="transport",
        date="2026-08-20",
    )
    _create_expense(client, description="Later meal", date="2026-09-20")

    response = client.get(
        EXPENSES,
        params={
            "trip_id": "trip_chunk2",
            "category": "food",
            "date_from": "2026-09-01",
            "date_to": "2026-09-10",
        },
    )
    assert response.status_code == 200
    assert _data(response) == [expected]


def test_expense_rejects_bad_filters_and_empty_update(client: TestClient) -> None:
    created = _create_expense(client)

    assert client.get(EXPENSES, params={"category": "unknown"}).status_code == 422
    assert (
        client.get(
            EXPENSES,
            params={"date_from": "2026-09-10", "date_to": "2026-09-01"},
        ).status_code
        == 422
    )
    assert (
        client.patch(f"{EXPENSES}/{created['expense_id']}", json={}).status_code == 422
    )


def test_seed_data_is_deterministic_and_idempotent(database_path: Path) -> None:
    settings = Settings(sqlite_path=database_path, seed_data=True)
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            assert len(_data(client.get(BUDGETS))) == 10
            assert len(_data(client.get(EXPENSES))) == 10


def test_seed_data_references_canonical_student_1_trips() -> None:
    assert {budget["trip_id"] for budget in SEED_BUDGETS} == set(TRIP_WINDOWS)
    assert {expense["trip_id"] for expense in SEED_EXPENSES} == set(TRIP_WINDOWS)
    for expense in SEED_EXPENSES:
        start_date, end_date = TRIP_WINDOWS[expense["trip_id"]]
        assert start_date <= expense["date"] <= end_date


def test_money_is_stored_as_exact_text(client: TestClient, database_path: Path) -> None:
    _create_budget(client)
    _create_expense(client)

    with closing(sqlite3.connect(database_path)) as connection:
        budget_money = connection.execute(
            "SELECT total_budget, typeof(total_budget) FROM budgets"
        ).fetchone()
        expense_money = connection.execute(
            "SELECT amount, typeof(amount) FROM expenses"
        ).fetchone()
    assert budget_money == ("2000.00", "text")
    assert expense_money == ("45.50", "text")


def test_records_persist_across_app_restarts(database_path: Path) -> None:
    settings = Settings(sqlite_path=database_path, seed_data=False)
    with TestClient(create_app(settings)) as client:
        budget = _create_budget(client)
        expense = _create_expense(client)

    with TestClient(create_app(settings)) as client:
        assert (
            _data(client.get(f"{BUDGETS}/{budget['budget_id']}"))["trip_id"]
            == "trip_chunk2"
        )
        assert (
            _data(client.get(f"{EXPENSES}/{expense['expense_id']}"))["description"]
            == "Dinner"
        )
