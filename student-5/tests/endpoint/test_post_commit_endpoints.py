from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest

BASE_URL = os.environ.get("STUDENT5_ENDPOINT_BASE_URL", "http://127.0.0.1:18005")
TRIP_ID = "trip_2026_melbourne_food_trail"
TRIP_DATE = "2026-11-13"
BUDGET_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "tripgenie/student-5/budget/2"))


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"{BASE_URL}/api/v1", timeout=15) as http:
        httpx.get(f"{BASE_URL}/ready", timeout=10).raise_for_status()
        yield http


@pytest.fixture
def created(client: httpx.Client) -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    for expense_id in ids:
        client.delete(f"/expenses/{expense_id}")


def expense_payload(**overrides: object) -> dict[str, Any]:
    return {
        "trip_id": TRIP_ID,
        "category": "food",
        "description": f"CI endpoint test {uuid.uuid4().hex[:8]}",
        "amount": "12.34",
        "currency": "AUD",
        "date": TRIP_DATE,
        "payment_method": "card",
    } | overrides


def create_expense(
    client: httpx.Client, created: list[str], **overrides: object
) -> dict[str, Any]:
    response = client.post("/expenses", json=expense_payload(**overrides))
    assert response.status_code == 201, response.text
    expense = response.json()["data"]
    created.append(expense["expense_id"])
    return expense


def summary(client: httpx.Client) -> dict[str, Any]:
    response = client.get(f"/budgets/{BUDGET_ID}/summary")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def detail_fields(response: httpx.Response) -> list[str]:
    return [detail["field"] for detail in response.json()["error"]["details"]]


def test_a_created_expense_is_stored_and_read_back(
    client: httpx.Client, created: list[str]
) -> None:
    expense = create_expense(client, created)

    response = client.get(f"/expenses/{expense['expense_id']}")

    assert response.status_code == 200, response.text
    stored = response.json()["data"]
    assert stored == expense
    assert stored["amount"] == "12.34"
    assert stored["trip_id"] == TRIP_ID
    assert stored["notes"] is None


def test_a_created_expense_is_listed_by_trip_and_category(
    client: httpx.Client, created: list[str]
) -> None:
    expense = create_expense(client, created, category="shopping")

    response = client.get(
        "/expenses", params={"trip_id": TRIP_ID, "category": "shopping"}
    )

    assert response.status_code == 200
    listed = response.json()["data"]
    assert expense["expense_id"] in [item["expense_id"] for item in listed]
    assert {item["category"] for item in listed} == {"shopping"}


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"amount": "0.00"}, "amount"),
        ({"amount": "10.005"}, "amount"),
        ({"category": "souvenirs"}, "category"),
        ({"currency": "aud"}, "currency"),
        ({"description": ""}, "description"),
    ],
    ids=["zero-amount", "sub-cent-amount", "unknown-category", "currency", "blank"],
)
def test_an_invalid_expense_is_rejected(
    client: httpx.Client, overrides: dict[str, object], field: str
) -> None:
    response = client.post("/expenses", json=expense_payload(**overrides))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in detail_fields(response)


def test_an_unknown_expense_is_not_found(client: httpx.Client) -> None:
    response = client.get(f"/expenses/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_the_summary_arithmetic_is_exact(client: httpx.Client) -> None:
    data = summary(client)

    assert data["budget_id"] == BUDGET_ID
    assert data["trip_id"] == TRIP_ID
    totals = {key: Decimal(value) for key, value in data["category_totals"].items()}
    assert Decimal(data["actual_spending"]) == sum(totals.values())
    assert Decimal(data["remaining_budget"]) == (
        Decimal(data["total_budget"])
        - Decimal(data["committed_costs"])
        - Decimal(data["actual_spending"])
    )
    assert set(data["providers"]) == {"transport", "accommodation", "activities"}


def test_the_summary_includes_a_new_expense_to_the_cent(
    client: httpx.Client, created: list[str]
) -> None:
    before = summary(client)
    create_expense(client, created, amount="12.34", category="food")
    after = summary(client)

    delta = Decimal("12.34")
    assert (
        Decimal(after["actual_spending"]) == Decimal(before["actual_spending"]) + delta
    )
    assert Decimal(after["category_totals"]["food"]) == (
        Decimal(before["category_totals"]["food"]) + delta
    )
    assert Decimal(after["remaining_budget"]) == (
        Decimal(before["remaining_budget"]) - delta
    )


def test_the_summary_flags_an_unconverted_currency(
    client: httpx.Client, created: list[str]
) -> None:
    before = summary(client)
    create_expense(client, created, amount="50.00", currency="USD")
    after = summary(client)

    assert after["actual_spending"] == before["actual_spending"]
    assert after["unconverted_expense_count"] == before["unconverted_expense_count"] + 1
    assert after["actual_spending_complete"] is False
    assert after["remaining_budget_complete"] is False


def test_an_unknown_budget_summary_is_not_found(client: httpx.Client) -> None:
    response = client.get(f"/budgets/{uuid.uuid4()}/summary")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_malformed_budget_id_is_rejected(client: httpx.Client) -> None:
    response = client.get("/budgets/not-a-uuid/summary")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
