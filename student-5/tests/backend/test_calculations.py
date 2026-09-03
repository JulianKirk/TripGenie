from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from student5_backend_service.calculations import calculate_summary
from student5_backend_service.models import (
    BudgetRecord,
    ExpenseRecord,
    ProviderCost,
)

NOW = datetime.now(UTC)
BUDGET_ID = UUID("11111111-1111-4111-8111-111111111111")


def _budget(total: str = "1000.00") -> BudgetRecord:
    return BudgetRecord(
        budget_id=BUDGET_ID,
        trip_id="trip_summary",
        currency="AUD",
        total_budget=total,
        created_at=NOW,
        updated_at=NOW,
    )


def _expense(amount: str, *, currency: str = "AUD") -> ExpenseRecord:
    return ExpenseRecord(
        expense_id=UUID("22222222-2222-4222-8222-222222222222"),
        trip_id="trip_summary",
        category="food",
        description="Dinner",
        amount=amount,
        currency=currency,
        date=date(2026, 9, 2),
        created_at=NOW,
        updated_at=NOW,
    )


def test_summary_uses_exact_decimal_arithmetic() -> None:
    providers = {
        "transport": ProviderCost(
            provider="transport",
            status="available",
            subtotal="200.20",
            currency="AUD",
        )
    }

    summary = calculate_summary(
        _budget(),
        [_expense("100.10"), _expense("50.05")],
        providers,
    )

    assert summary.actual_spending == Decimal("150.15")
    assert summary.committed_costs == Decimal("200.20")
    assert summary.remaining_budget == Decimal("649.65")
    assert summary.remaining_budget_complete is True


def test_summary_can_report_a_negative_remaining_budget() -> None:
    summary = calculate_summary(_budget("100.00"), [_expense("120.00")], {})

    assert summary.remaining_budget == Decimal("-20.00")


def test_summary_reports_known_zero_when_there_are_no_expenses() -> None:
    summary = calculate_summary(_budget(), [], {})

    assert summary.actual_spending == Decimal("0.00")
    assert summary.actual_spending_complete is True
    assert all(total == Decimal("0.00") for total in summary.category_totals.values())


def test_mixed_expense_currency_is_visible_and_not_aggregated() -> None:
    summary = calculate_summary(
        _budget(),
        [_expense("25.00"), _expense("50.00", currency="USD")],
        {},
    )

    assert summary.actual_spending == Decimal("25.00")
    assert summary.actual_spending_complete is False
    assert summary.unconverted_expense_count == 1
    assert summary.remaining_budget_complete is False


def test_unavailable_provider_makes_committed_total_incomplete() -> None:
    providers = {
        "transport": ProviderCost(
            provider="transport", status="unavailable", detail="timed out"
        )
    }

    summary = calculate_summary(_budget(), [], providers)

    assert summary.committed_costs == Decimal("0.00")
    assert summary.committed_costs_complete is False
    assert summary.remaining_budget_complete is False
