from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import FastAPI, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .accommodation_client import AccommodationApiClient
from .ai_mode_client import AiModeClient
from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError
from .models import (
    BudgetAnalysisRequest,
    BudgetCreate,
    BudgetUpdate,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseUpdate,
)
from .service import BackendService
from .transport_client import TransportApiClient
from .trips_client import TripsApiClient


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
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields failed validation.",
                "details": [
                    {
                        "field": ".".join(
                            str(part) for part in error["loc"] if part != "body"
                        )
                        or "body",
                        "issue": error["msg"],
                    }
                    for error in exc.errors()
                ],
            }
        },
    )


def create_app(
    settings: Settings | None = None,
    *,
    database_transport: httpx.BaseTransport | None = None,
    trips_transport: httpx.BaseTransport | None = None,
    provider_transport: httpx.BaseTransport | None = None,
    accommodation_transport: httpx.BaseTransport | None = None,
    ai_mode_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = DatabaseApiClient(settings, transport=database_transport)
    trips = TripsApiClient(settings, transport=trips_transport)
    transport = TransportApiClient(settings, transport=provider_transport)
    accommodation = AccommodationApiClient(settings, transport=accommodation_transport)
    ai_mode = AiModeClient(settings, transport=ai_mode_transport)
    service = BackendService(
        database, trips, transport, accommodation, ai_mode, settings
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        database.close()
        trips.close()
        transport.close()
        accommodation.close()
        ai_mode.close()

    app = FastAPI(title="TripGenie Student 5 Backend", lifespan=lifespan)

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
        database_ready = service.ready()
        return {
            "data": {
                "status": "healthy" if database_ready else "degraded",
                "service": settings.service_name,
                "dependencies": {"database": database_ready},
            }
        }

    @app.get("/ready")
    def ready(response: Response) -> dict[str, object]:
        database_ready = service.ready()
        if not database_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "data": {
                "status": "ready" if database_ready else "not_ready",
                "service": settings.service_name,
                "dependencies": {"database": database_ready},
            }
        }

    prefix = settings.api_prefix

    @app.get(f"{prefix}/trips")
    def list_trips() -> dict[str, Any]:
        return _json_data(service.list_trips())

    @app.get(f"{prefix}/budgets")
    def list_budgets(
        trip_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    ) -> dict[str, Any]:
        return _json_data(service.list_budgets(trip_id))

    @app.post(f"{prefix}/budgets", status_code=status.HTTP_201_CREATED)
    def create_budget(payload: BudgetCreate) -> dict[str, Any]:
        return _json_data(service.create_budget(payload))

    @app.get(f"{prefix}/budgets/{{budget_id}}")
    def get_budget(budget_id: UUID) -> dict[str, Any]:
        return _json_data(service.get_budget(budget_id))

    @app.patch(f"{prefix}/budgets/{{budget_id}}")
    def update_budget(budget_id: UUID, payload: BudgetUpdate) -> dict[str, Any]:
        return _json_data(service.update_budget(budget_id, payload))

    @app.delete(f"{prefix}/budgets/{{budget_id}}")
    def delete_budget(budget_id: UUID) -> dict[str, Any]:
        return _json_data(service.delete_budget(budget_id))

    @app.get(f"{prefix}/budgets/{{budget_id}}/summary")
    def budget_summary(budget_id: UUID) -> dict[str, Any]:
        return _json_data(service.budget_summary(budget_id))

    @app.post(f"{prefix}/budgets/{{budget_id}}/ai-analysis")
    def budget_analysis(
        budget_id: UUID, payload: BudgetAnalysisRequest
    ) -> dict[str, Any]:
        return _json_data(service.budget_analysis(budget_id, payload))

    @app.get(f"{prefix}/expenses")
    def list_expenses(
        trip_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        category: ExpenseCategory | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        return _json_data(
            service.list_expenses(
                trip_id=trip_id,
                category=category,
                date_from=date_from,
                date_to=date_to,
            )
        )

    @app.post(f"{prefix}/expenses", status_code=status.HTTP_201_CREATED)
    def create_expense(payload: ExpenseCreate) -> dict[str, Any]:
        return _json_data(service.create_expense(payload))

    @app.get(f"{prefix}/expenses/{{expense_id}}")
    def get_expense(expense_id: UUID) -> dict[str, Any]:
        return _json_data(service.get_expense(expense_id))

    @app.patch(f"{prefix}/expenses/{{expense_id}}")
    def update_expense(expense_id: UUID, payload: ExpenseUpdate) -> dict[str, Any]:
        return _json_data(service.update_expense(expense_id, payload))

    @app.delete(f"{prefix}/expenses/{{expense_id}}")
    def delete_expense(expense_id: UUID) -> dict[str, Any]:
        return _json_data(service.delete_expense(expense_id))

    return app


app = create_app()
