from decimal import Decimal

import pytest
from pydantic import ValidationError
from student5_database_service.models import (
    BudgetCreate,
    BudgetUpdate,
    ExpenseCreate,
    ExpenseUpdate,
)


def test_budget_uses_decimal_money_and_rejects_overallocation() -> None:
    budget = BudgetCreate(
        trip_id="trip_demo",
        currency="AUD",
        total_budget="100.00",
        food_budget="25.50",
    )
    assert budget.food_budget == Decimal("25.50")

    with pytest.raises(ValidationError, match="must not exceed"):
        BudgetCreate(
            trip_id="trip_demo",
            currency="AUD",
            total_budget="100.00",
            food_budget="100.01",
        )


@pytest.mark.parametrize("amount", ["0.00", "-1.00", "1.001"])
def test_expense_rejects_invalid_money(amount: str) -> None:
    with pytest.raises(ValidationError):
        ExpenseCreate(
            trip_id="trip_demo",
            category="food",
            description="Lunch",
            amount=amount,
            currency="AUD",
            date="2026-09-02",
        )


def test_expense_rejects_unknown_category_currency_and_date() -> None:
    with pytest.raises(ValidationError):
        ExpenseCreate(
            trip_id="trip_demo",
            category="entertainment",
            description="Show",
            amount="20.00",
            currency="aud",
            date="not-a-date",
        )


def test_expense_accepts_blank_optional_text() -> None:
    expense = ExpenseCreate(
        trip_id="trip_demo",
        category="food",
        description="Lunch",
        amount="20.00",
        currency="AUD",
        date="2026-09-02",
        payment_method="",
        notes="",
    )
    update = ExpenseUpdate(payment_method="", notes="")

    assert expense.payment_method is None
    assert expense.notes is None
    assert update.payment_method is None
    assert update.notes is None


def test_update_models_track_an_empty_patch() -> None:
    assert BudgetUpdate().model_fields_set == set()
    assert ExpenseUpdate().model_fields_set == set()
