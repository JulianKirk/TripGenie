from __future__ import annotations

from datetime import date
from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_error
from .models import (
    BudgetCreate,
    BudgetRecord,
    BudgetUpdate,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseRecord,
    ExpenseUpdate,
)

T = TypeVar("T")


class DatabaseApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._prefix = settings.database_api_prefix
        self._client = httpx.Client(
            base_url=settings.database_api_base_url,
            timeout=settings.database_api_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def ready(self) -> bool:
        try:
            return self._client.get("/ready").status_code == 200
        except httpx.RequestError:
            return False

    def _request(
        self,
        method: str,
        path: str,
        response_type: Any,
        expected_status: int = 200,
        **kwargs: Any,
    ) -> T:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise dependency_error("database", "request timed out") from exc
        except httpx.RequestError as exc:
            raise dependency_error("database", "request failed") from exc

        if response.status_code != expected_status:
            if response.status_code in {400, 404, 409, 422, 503}:
                try:
                    error = response.json()["error"]
                    raise ApiError(
                        response.status_code,
                        str(error["code"]),
                        str(error["message"]),
                        list(error.get("details", [])),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise bad_gateway("database", "malformed error envelope") from exc
            raise dependency_error(
                "database", f"unexpected HTTP {response.status_code}"
            )

        try:
            payload = response.json()["data"]
            return TypeAdapter(response_type).validate_python(payload)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise bad_gateway("database", "malformed success envelope") from exc

    def list_budgets(self, trip_id: str | None = None) -> list[BudgetRecord]:
        params = {"trip_id": trip_id} if trip_id else None
        return self._request(
            "GET", f"{self._prefix}/budgets", list[BudgetRecord], params=params
        )

    def create_budget(self, payload: BudgetCreate) -> BudgetRecord:
        return self._request(
            "POST",
            f"{self._prefix}/budgets",
            BudgetRecord,
            201,
            json=payload.model_dump(mode="json", exclude_none=True),
        )

    def get_budget(self, budget_id: UUID) -> BudgetRecord:
        return self._request("GET", f"{self._prefix}/budgets/{budget_id}", BudgetRecord)

    def update_budget(self, budget_id: UUID, payload: BudgetUpdate) -> BudgetRecord:
        return self._request(
            "PATCH",
            f"{self._prefix}/budgets/{budget_id}",
            BudgetRecord,
            json=payload.model_dump(mode="json", exclude_unset=True),
        )

    def delete_budget(self, budget_id: UUID) -> dict[str, Any]:
        return self._request(
            "DELETE", f"{self._prefix}/budgets/{budget_id}", dict[str, Any]
        )

    def list_expenses(
        self,
        *,
        trip_id: str | None = None,
        category: ExpenseCategory | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ExpenseRecord]:
        params = {
            key: value.value if isinstance(value, ExpenseCategory) else str(value)
            for key, value in {
                "trip_id": trip_id,
                "category": category,
                "date_from": date_from,
                "date_to": date_to,
            }.items()
            if value is not None
        }
        return self._request(
            "GET", f"{self._prefix}/expenses", list[ExpenseRecord], params=params
        )

    def create_expense(self, payload: ExpenseCreate) -> ExpenseRecord:
        return self._request(
            "POST",
            f"{self._prefix}/expenses",
            ExpenseRecord,
            201,
            json=payload.model_dump(mode="json", exclude_none=True),
        )

    def get_expense(self, expense_id: UUID) -> ExpenseRecord:
        return self._request(
            "GET", f"{self._prefix}/expenses/{expense_id}", ExpenseRecord
        )

    def update_expense(self, expense_id: UUID, payload: ExpenseUpdate) -> ExpenseRecord:
        return self._request(
            "PATCH",
            f"{self._prefix}/expenses/{expense_id}",
            ExpenseRecord,
            json=payload.model_dump(mode="json", exclude_unset=True),
        )

    def delete_expense(self, expense_id: UUID) -> dict[str, Any]:
        return self._request(
            "DELETE", f"{self._prefix}/expenses/{expense_id}", dict[str, Any]
        )
