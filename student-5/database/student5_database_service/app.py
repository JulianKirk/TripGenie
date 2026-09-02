from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import Settings
from .errors import ApiError
from .models import (
    BudgetCreate,
    BudgetUpdate,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseUpdate,
)
from .repository import DatabaseRepository


def _json_data(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        payload = [item.model_dump(mode="json") for item in value]
    elif hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    else:
        payload = value
    return {"data": payload}


def _validation_response(
    exc: RequestValidationError | ValidationError,
) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part != "body")
            or "body",
            "issue": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields failed validation.",
                "details": details,
            }
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = DatabaseRepository(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        yield

    app = FastAPI(title="TripGenie Student 5 Database", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _validation_response(exc)

    @app.exception_handler(ValidationError)
    async def model_validation_handler(
        _: Request, exc: ValidationError
    ) -> JSONResponse:
        return _validation_response(exc)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"data": {"status": "healthy", "service": settings.service_name}}

    @app.get("/ready")
    def ready() -> dict[str, object]:
        return {"data": {"status": "ready", "service": settings.service_name}}

    prefix = settings.api_prefix

    @app.get(f"{prefix}/budgets")
    def list_budgets(
        trip_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    ) -> dict[str, Any]:
        return _json_data(repository.list_budgets(trip_id))

    @app.post(f"{prefix}/budgets", status_code=status.HTTP_201_CREATED)
    def create_budget(payload: BudgetCreate) -> dict[str, Any]:
        return _json_data(repository.create_budget(payload))

    @app.get(f"{prefix}/budgets/{{budget_id}}")
    def get_budget(budget_id: UUID) -> dict[str, Any]:
        return _json_data(repository.get_budget(budget_id))

    @app.patch(f"{prefix}/budgets/{{budget_id}}")
    def update_budget(budget_id: UUID, payload: BudgetUpdate) -> dict[str, Any]:
        return _json_data(repository.update_budget(budget_id, payload))

    @app.delete(f"{prefix}/budgets/{{budget_id}}")
    def delete_budget(budget_id: UUID) -> dict[str, Any]:
        repository.delete_budget(budget_id)
        return _json_data({"id": str(budget_id), "deleted": True})

    @app.get(f"{prefix}/expenses")
    def list_expenses(
        trip_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        category: ExpenseCategory | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        if date_from and date_to and date_from > date_to:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "date_from must not be later than date_to.",
                [{"field": "date_from", "issue": "must not be later than date_to"}],
            )
        return _json_data(
            repository.list_expenses(trip_id, category, date_from, date_to)
        )

    @app.post(f"{prefix}/expenses", status_code=status.HTTP_201_CREATED)
    def create_expense(payload: ExpenseCreate) -> dict[str, Any]:
        return _json_data(repository.create_expense(payload))

    @app.get(f"{prefix}/expenses/{{expense_id}}")
    def get_expense(expense_id: UUID) -> dict[str, Any]:
        return _json_data(repository.get_expense(expense_id))

    @app.patch(f"{prefix}/expenses/{{expense_id}}")
    def update_expense(expense_id: UUID, payload: ExpenseUpdate) -> dict[str, Any]:
        return _json_data(repository.update_expense(expense_id, payload))

    @app.delete(f"{prefix}/expenses/{{expense_id}}")
    def delete_expense(expense_id: UUID) -> dict[str, Any]:
        repository.delete_expense(expense_id)
        return _json_data({"id": str(expense_id), "deleted": True})

    return app


app = create_app()
