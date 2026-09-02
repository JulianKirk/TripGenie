from __future__ import annotations

from datetime import date
from uuid import UUID

from .ai_analysis import build_budget_analysis_prompt
from .ai_mode_client import AiModeClient
from .calculations import calculate_summary
from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError, bad_gateway, date_outside_trip
from .models import (
    BudgetAnalysisRequest,
    BudgetAnalysisResponse,
    BudgetCreate,
    BudgetRecord,
    BudgetSummary,
    BudgetUpdate,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseRecord,
    ExpenseUpdate,
    ProviderCost,
)
from .transport_client import TransportApiClient
from .trips_client import TripsApiClient


class BackendService:
    def __init__(
        self,
        database: DatabaseApiClient,
        trips: TripsApiClient,
        transport: TransportApiClient,
        ai_mode: AiModeClient,
        settings: Settings,
    ) -> None:
        self.database = database
        self.trips = trips
        self.transport = transport
        self.ai_mode = ai_mode
        self.settings = settings

    def ready(self) -> bool:
        return self.database.ready()

    def _validate_trip(self, trip_id: str, expense_date: date | None = None) -> None:
        trip = self.trips.get_trip(trip_id)
        if trip is not None and expense_date is not None:
            if not trip.start_date <= expense_date <= trip.end_date:
                raise date_outside_trip()

    def list_budgets(self, trip_id: str | None = None) -> list[BudgetRecord]:
        return self.database.list_budgets(trip_id)

    def create_budget(self, payload: BudgetCreate) -> BudgetRecord:
        self._validate_trip(payload.trip_id)
        return self.database.create_budget(payload)

    def get_budget(self, budget_id: UUID) -> BudgetRecord:
        return self.database.get_budget(budget_id)

    def update_budget(self, budget_id: UUID, payload: BudgetUpdate) -> BudgetRecord:
        if payload.trip_id is not None:
            self._validate_trip(payload.trip_id)
        return self.database.update_budget(budget_id, payload)

    def delete_budget(self, budget_id: UUID) -> dict[str, object]:
        return self.database.delete_budget(budget_id)

    def list_expenses(
        self,
        *,
        trip_id: str | None = None,
        category: ExpenseCategory | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ExpenseRecord]:
        return self.database.list_expenses(
            trip_id=trip_id,
            category=category,
            date_from=date_from,
            date_to=date_to,
        )

    def create_expense(self, payload: ExpenseCreate) -> ExpenseRecord:
        self._validate_trip(payload.trip_id, payload.date)
        return self.database.create_expense(payload)

    def get_expense(self, expense_id: UUID) -> ExpenseRecord:
        return self.database.get_expense(expense_id)

    def update_expense(self, expense_id: UUID, payload: ExpenseUpdate) -> ExpenseRecord:
        if payload.trip_id is not None or payload.date is not None:
            current = self.database.get_expense(expense_id)
            self._validate_trip(
                payload.trip_id or current.trip_id,
                payload.date or current.date,
            )
        return self.database.update_expense(expense_id, payload)

    def delete_expense(self, expense_id: UUID) -> dict[str, object]:
        return self.database.delete_expense(expense_id)

    def budget_summary(self, budget_id: UUID) -> BudgetSummary:
        budget = self.database.get_budget(budget_id)
        expenses = self.database.list_expenses(trip_id=budget.trip_id)
        providers = {
            "transport": self.transport.committed_cost(budget.trip_id, budget.currency),
            "accommodation": ProviderCost(
                provider="accommodation",
                status="unavailable",
                detail="provider contract is not available",
            ),
            "activities": ProviderCost(
                provider="activities",
                status="unavailable",
                detail="provider contract is not available",
            ),
        }
        return calculate_summary(budget, expenses, providers)

    def budget_analysis(
        self, budget_id: UUID, request: BudgetAnalysisRequest
    ) -> BudgetAnalysisResponse:
        summary = self.budget_summary(budget_id)
        expenses = self.database.list_expenses(trip_id=summary.trip_id)
        prompt = build_budget_analysis_prompt(self.settings, summary, expenses, request)
        metadata = {
            "feature": "student-5-budget-analysis",
            "trip_id": summary.trip_id,
            "attempt": "1",
        }
        try:
            result = self.ai_mode.generate(
                prompt=prompt,
                correlation_id=f"budget_{budget_id.hex}",
                metadata=metadata,
            )
            if self._analysis_is_grounded(result, summary):
                return result
        except ApiError as error:
            if error.code != "INVALID_DEPENDENCY_RESPONSE":
                raise

        retry_prompt = (
            f"{prompt}\n\nYour previous response was invalid or ungrounded. "
            "Return valid schema-conforming JSON. In the overview, quote at least one "
            "exact currency amount from the authoritative key facts."
        )
        result = self.ai_mode.generate(
            prompt=retry_prompt,
            correlation_id=f"budget_{budget_id.hex}_retry",
            metadata=metadata | {"attempt": "2"},
        )
        if not self._analysis_is_grounded(result, summary):
            raise bad_gateway("ai_mode", "analysis was not grounded in budget totals")
        return result

    @staticmethod
    def _analysis_is_grounded(
        result: BudgetAnalysisResponse, summary: BudgetSummary
    ) -> bool:
        text = " ".join(
            (
                result.analysis.overview,
                *result.analysis.risks,
                *result.analysis.recommendations,
            )
        )
        amounts = (
            summary.total_budget,
            summary.actual_spending,
            summary.committed_costs,
            summary.remaining_budget,
        )
        return summary.currency in text and any(
            f"{amount:.2f}" in text for amount in amounts
        )
