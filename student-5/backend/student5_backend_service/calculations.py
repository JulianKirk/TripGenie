from __future__ import annotations

from decimal import Decimal

from .models import (
    BudgetRecord,
    BudgetSummary,
    ExpenseCategory,
    ExpenseRecord,
    ProviderCost,
    ProviderStatus,
)


def calculate_summary(
    budget: BudgetRecord,
    expenses: list[ExpenseRecord],
    providers: dict[str, ProviderCost],
) -> BudgetSummary:
    category_totals = {category: Decimal("0.00") for category in ExpenseCategory}
    unconverted_expense_count = 0

    for expense in expenses:
        if expense.currency != budget.currency:
            unconverted_expense_count += 1
            continue
        category_totals[expense.category] += expense.amount

    actual_spending = sum(category_totals.values(), Decimal("0.00"))
    available_costs = [
        provider.subtotal
        for provider in providers.values()
        if provider.status == ProviderStatus.AVAILABLE
        and provider.currency == budget.currency
        and provider.subtotal is not None
    ]
    committed_costs = sum(available_costs, Decimal("0.00"))
    committed_complete = all(
        provider.status == ProviderStatus.AVAILABLE
        and provider.currency == budget.currency
        and provider.subtotal is not None
        for provider in providers.values()
    )
    actual_complete = unconverted_expense_count == 0

    return BudgetSummary(
        budget_id=budget.budget_id,
        trip_id=budget.trip_id,
        currency=budget.currency,
        total_budget=budget.total_budget,
        actual_spending=actual_spending,
        actual_spending_complete=actual_complete,
        unconverted_expense_count=unconverted_expense_count,
        committed_costs=committed_costs,
        committed_costs_complete=committed_complete,
        remaining_budget=budget.total_budget - actual_spending - committed_costs,
        remaining_budget_complete=actual_complete and committed_complete,
        category_totals=category_totals,
        providers=providers,
    )
