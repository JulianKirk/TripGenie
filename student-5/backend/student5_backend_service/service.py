from __future__ import annotations

import json
import logging
from datetime import date
from importlib import resources
from time import perf_counter
from uuid import UUID, uuid4

from pydantic import ValidationError

from . import agent_runs
from .accommodation_client import AccommodationApiClient
from .activity_client import ActivityApiClient
from .ai_analysis import build_budget_analysis_prompt
from .ai_mode_client import AiModeClient
from .calculations import calculate_summary
from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError, bad_gateway, date_outside_trip
from .models import (
    AgentAppliedChange,
    AgentReviewRequest,
    AgentRunRequest,
    AgentRunView,
    BudgetAnalysisRequest,
    BudgetAnalysisResponse,
    BudgetCreate,
    BudgetFields,
    BudgetRecord,
    BudgetSummary,
    BudgetUpdate,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseRecord,
    ExpenseUpdate,
    McpActionResult,
    RagAnswer,
    RagQueryRequest,
    TripRecord,
)
from .multi_agent_client import MultiAgentClient
from .rag_client import RagClient
from .transport_client import TransportApiClient
from .trips_client import TripsApiClient

logger = logging.getLogger(__name__)

MCP_ACTIONS = {
    "budget-summary": "Get the spending summary for this budget.",
    "expenses": "List the 20 most recent expenses for this trip.",
}
MCP_SYSTEM_PROMPT_ASSET = "budget_tools_v1.md"


def _disabled(code: str, field: str, name: str) -> ApiError:
    return ApiError(
        503,
        code,
        f"{name} is disabled in this environment.",
        [{"field": field, "issue": "disabled by configuration"}],
    )


class BackendService:
    def __init__(
        self,
        database: DatabaseApiClient,
        trips: TripsApiClient,
        transport: TransportApiClient,
        accommodation: AccommodationApiClient,
        activities: ActivityApiClient,
        ai_mode: AiModeClient,
        settings: Settings,
        rag: RagClient,
        multi_agent: MultiAgentClient,
    ) -> None:
        self.database = database
        self.trips = trips
        self.transport = transport
        self.accommodation = accommodation
        self.activities = activities
        self.ai_mode = ai_mode
        self.settings = settings
        self.rag = rag
        self.multi_agent = multi_agent

    def ready(self) -> bool:
        return self.database.ready()

    def integrations(self) -> dict[str, str]:
        return {
            "rag": "enabled" if self.settings.rag_enabled else "disabled",
            "mcp": "enabled" if self.settings.mcp_enabled else "disabled",
            "multi_agent": (
                "enabled" if self.settings.multi_agent_enabled else "disabled"
            ),
        }

    def _multi_agent(self) -> MultiAgentClient:
        if not self.settings.multi_agent_enabled:
            raise _disabled(
                "MULTI_AGENT_DISABLED", "multi_agent", "Budget review agents"
            )
        return self.multi_agent

    def start_agent_run(
        self, budget_id: UUID, payload: AgentRunRequest
    ) -> AgentRunView:
        client = self._multi_agent()
        budget = self.database.get_budget(budget_id)
        worker_system = (
            resources.files("student5_backend_service")
            .joinpath("prompts", agent_runs.WORKER_PROMPT_ASSET)
            .read_text(encoding="utf-8")
        )
        body = agent_runs.build_run_request(
            self.settings, budget, payload.question, worker_system
        )
        run = client.start_run(body)
        logger.info(
            "agent_run_started correlation_id=%s run_id=%s budget_id=%s",
            body["correlation_id"],
            run.get("run_id"),
            budget_id,
        )
        return agent_runs.to_view(run, budget)

    def _agent_view(
        self, client: MultiAgentClient, run: dict, budget: BudgetRecord
    ) -> AgentRunView:
        history = (
            client.history(run["run_id"])
            if run.get("status") in agent_runs.TERMINAL_STATUSES
            else None
        )
        return agent_runs.to_view(run, budget, history)

    def get_agent_run(self, budget_id: UUID, run_id: str) -> AgentRunView:
        client = self._multi_agent()
        budget = self.database.get_budget(budget_id)
        run = client.get_run(run_id)
        agent_runs.ensure_feature(run, run_id)
        return self._agent_view(client, run, budget)

    def review_agent_run(
        self, budget_id: UUID, run_id: str, decision: AgentReviewRequest
    ) -> AgentRunView:
        client = self._multi_agent()
        budget = self.database.get_budget(budget_id)
        run = client.get_run(run_id)
        agent_runs.ensure_feature(run, run_id)
        decided = client.review(run_id, agent_runs.review_body(run, decision))

        applied: list[AgentAppliedChange] = []
        apply_error = None
        if decided.get("approved_actions"):
            applied, apply_error = self._apply_allocations(decided, budget)
        logger.info(
            "agent_run_decided run_id=%s decision=%s applied=%d apply_error=%s",
            run_id,
            decision.decision,
            len(applied),
            apply_error is not None,
        )
        view = self._agent_view(client, decided, budget)
        return view.model_copy(
            update={"applied_changes": applied, "apply_error": apply_error}
        )

    def _apply_allocations(
        self, run: dict, budget: BudgetRecord
    ) -> tuple[list[AgentAppliedChange], str | None]:
        if not agent_runs.is_grounded(run, budget.budget_id):
            return [], (
                "The answer was not grounded in this budget's tool results, "
                "so no allocation was changed."
            )
        try:
            changes = agent_runs.allocation_changes(run)
            BudgetFields.model_validate(
                budget.model_dump(include=set(BudgetFields.model_fields)) | changes
            )
        except ValidationError:
            return [], (
                "The approved allocations are invalid or would exceed the total "
                "budget, so no allocation was changed."
            )
        try:
            self.database.update_budget(budget.budget_id, BudgetUpdate(**changes))
        except ApiError as error:
            return [], f"The budget could not be updated: {error.message}"
        return [
            AgentAppliedChange(
                category=field.removesuffix("_budget"),
                previous=f"{getattr(budget, field):.2f}",
                new=f"{value:.2f}",
            )
            for field, value in changes.items()
        ], None

    def rag_query(self, request: RagQueryRequest) -> RagAnswer:
        if not self.settings.rag_enabled:
            raise _disabled("RAG_DISABLED", "rag", "The knowledge assistant")
        correlation_id = f"student5-rag-{uuid4().hex[:12]}"
        started = perf_counter()
        outcome = "error"
        try:
            answer = self.rag.query(request.question, correlation_id)
            outcome = answer.confidence_category
            return answer
        except ApiError as error:
            outcome = error.code
            raise
        finally:
            logger.info(
                "rag_query correlation_id=%s outcome=%s duration_ms=%d",
                correlation_id,
                outcome,
                (perf_counter() - started) * 1000,
            )

    def run_mcp_action(self, budget_id: UUID, action: str) -> McpActionResult:
        if not self.settings.mcp_enabled:
            raise _disabled("MCP_DISABLED", "mcp", "The MCP tool server")
        if action not in MCP_ACTIONS:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "The MCP action is not supported.",
                [{"field": "action", "issue": f"must be one of {sorted(MCP_ACTIONS)}"}],
            )
        budget = self.database.get_budget(budget_id)
        correlation_id = f"student5-mcp-{uuid4().hex[:12]}"
        system = (
            resources.files("student5_backend_service")
            .joinpath("prompts", MCP_SYSTEM_PROMPT_ASSET)
            .read_text(encoding="utf-8")
        )
        prompt = json.dumps(
            {
                "request": MCP_ACTIONS[action],
                "budget_id": str(budget.budget_id),
                "trip_id": budget.trip_id,
            }
        )
        started = perf_counter()
        outcome = "error"
        try:
            generated = self.ai_mode.run_tools(
                prompt=prompt,
                system=system,
                correlation_id=correlation_id,
                metadata={
                    "feature": "student-5-budget-tools",
                    "trip_id": budget.trip_id,
                },
            )
            outcome = "ok"
        except ApiError as error:
            outcome = error.code
            raise
        finally:
            duration_ms = int((perf_counter() - started) * 1000)
            logger.info(
                "mcp_action correlation_id=%s action=%s outcome=%s duration_ms=%d",
                correlation_id,
                action,
                outcome,
                duration_ms,
            )
        return McpActionResult(
            action=action,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
            run_id=generated.run_id,
            model=generated.model,
            provider=generated.provider,
            answer=generated.response,
            tools=generated.tools,
        )

    def list_trips(self) -> list[TripRecord]:
        return self.trips.list_trips()

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
            "accommodation": self.accommodation.committed_cost(
                budget.trip_id, budget.currency
            ),
            "activities": self.activities.committed_cost(
                budget.trip_id, budget.currency
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
            result, used_tools = self.ai_mode.generate(
                prompt=prompt,
                correlation_id=f"budget_{budget_id.hex}",
                metadata=metadata,
            )
        except ApiError as error:
            if error.code != "INVALID_DEPENDENCY_RESPONSE" or not error.retryable:
                raise
        else:
            if self._analysis_is_grounded(result, summary):
                return result
            if used_tools:
                raise bad_gateway(
                    "ai_mode",
                    "analysis was not grounded and was not retried after tool calls",
                )

        retry_prompt = (
            f"{prompt}\n\nYour previous response was invalid or ungrounded. "
            "Return valid schema-conforming JSON. In the overview, quote at least one "
            "exact currency amount from the authoritative key facts."
        )
        result, _ = self.ai_mode.generate(
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
