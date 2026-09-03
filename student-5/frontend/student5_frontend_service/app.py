from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .client import BackendClient, BackendError
from .config import Settings

PACKAGE_ROOT = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
BUDGET_FIELDS = (
    "trip_id",
    "currency",
    "total_budget",
    "accommodation_budget",
    "transport_budget",
    "activities_budget",
    "food_budget",
    "other_budget",
)
EXPENSE_FIELDS = (
    "trip_id",
    "category",
    "description",
    "amount",
    "currency",
    "date",
    "payment_method",
    "notes",
)
CATEGORIES = ("accommodation", "transport", "activities", "food", "shopping", "other")
FIELD_LABELS = {
    "trip_id": "Trip",
    "currency": "Currency",
    "total_budget": "Total budget",
    "accommodation_budget": "Accommodation allocation",
    "transport_budget": "Transport allocation",
    "activities_budget": "Activities allocation",
    "food_budget": "Food allocation",
    "other_budget": "Other allocation",
    "category": "Category",
    "description": "Description",
    "amount": "Amount",
    "date": "Date",
}


def _fields(form: Any, names: tuple[str, ...]) -> dict[str, str]:
    return {name: str(form.get(name, "")).strip() for name in names}


def _friendly_issue(field: str, issue: str) -> str:
    label = FIELD_LABELS.get(field, field.replace("_", " ").title())
    lowered = issue.lower()
    if field == "currency" and "pattern" in lowered:
        return "Currency must use three uppercase letters, for example AUD."
    if "field required" in lowered:
        return f"{label} is required."
    if "greater than or equal to 0" in lowered:
        return f"{label} must be zero or more."
    if "greater than 0" in lowered:
        return f"{label} must be greater than zero."
    if field == "date" and "valid date" in lowered:
        return "Enter a valid date."
    if lowered.startswith("must "):
        return f"{label} {issue}."
    return f"{label}: {issue.rstrip('.')}."


def _errors_by_field(error: BackendError) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for detail in error.details:
        field = str(detail.get("field", "form"))
        issue = str(detail.get("issue", error))
        grouped.setdefault(field, []).append(_friendly_issue(field, issue))
    return grouped


def create_app(
    settings: Settings | None = None,
    *,
    backend_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    backend = BackendClient(settings.backend_base_url, transport=backend_transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        backend.close()

    app = FastAPI(title="TripGenie Student 5 Frontend", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")

    def render(
        request: Request,
        content_template: str,
        *,
        page_title: str,
        budgets: list[dict[str, Any]] | None = None,
        **context: Any,
    ) -> Response:
        template = (
            "partials/app_shell.html"
            if request.headers.get("HX-Request", "").lower() == "true"
            else "page.html"
        )
        return TEMPLATES.TemplateResponse(
            request,
            template,
            {
                "page_title": page_title,
                "content_template": content_template,
                "budgets": budgets or [],
                "categories": CATEGORIES,
                **context,
            },
        )

    def list_budgets() -> list[dict[str, Any]]:
        return backend.request("GET", "/budgets")

    def trip_context(
        budgets: list[dict[str, Any]], *records: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            trips = backend.request("GET", "/trips")
            trip_error = None
        except BackendError as error:
            trips, trip_error = [], error
        trips_by_id = {trip["id"]: trip for trip in trips}
        for budget in [*budgets, *records]:
            budget["trip"] = trips_by_id.get(budget["trip_id"])
        return {"trips": trips, "trip_error": trip_error}

    def error_page(request: Request, error: BackendError) -> Response:
        return render(
            request,
            "partials/error_state.html",
            page_title="Budgets unavailable",
            error=error,
        )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"data": {"status": "healthy", "service": settings.service_name}}

    @app.get("/ready")
    def ready() -> Response:
        available = backend.ready()
        return JSONResponse(
            {
                "data": {
                    "status": "ready" if available else "not_ready",
                    "service": settings.service_name,
                }
            },
            status_code=200 if available else 503,
        )

    @app.get("/")
    def browse(request: Request) -> Response:
        try:
            budgets = list_budgets()
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/budget_list.html",
            page_title="Budgets",
            budgets=budgets,
            **trip_context(budgets),
        )

    @app.get("/budgets/new")
    def new_budget(request: Request) -> Response:
        try:
            budgets = list_budgets()
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/budget_form.html",
            page_title="Create budget",
            budgets=budgets,
            **trip_context(budgets),
            form={
                "currency": "AUD",
                **{name: "0.00" for name in BUDGET_FIELDS[3:]},
            },
            errors={},
            action="/budgets",
            heading="Create budget",
        )

    @app.post("/budgets")
    async def create_budget(request: Request) -> Response:
        form = _fields(await request.form(), BUDGET_FIELDS)
        try:
            budget = backend.request("POST", "/budgets", json=form)
        except BackendError as error:
            try:
                budgets = list_budgets()
            except BackendError:
                budgets = []
            return render(
                request,
                "partials/budget_form.html",
                page_title="Create budget",
                budgets=budgets,
                form=form,
                errors=_errors_by_field(error),
                form_error=error,
                action="/budgets",
                heading="Create budget",
            )
        return RedirectResponse(f"/budgets/{budget['budget_id']}", status_code=303)

    @app.get("/budgets/{budget_id}")
    def budget_detail(
        request: Request,
        budget_id: str,
        category: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> Response:
        try:
            budgets = list_budgets()
            budget = backend.request("GET", f"/budgets/{budget_id}")
            params = {
                key: value
                for key, value in {
                    "trip_id": budget["trip_id"],
                    "category": category,
                    "date_from": date_from,
                    "date_to": date_to,
                }.items()
                if value
            }
            expenses = backend.request("GET", "/expenses", params=params)
        except BackendError as error:
            return error_page(request, error)
        try:
            summary = backend.request("GET", f"/budgets/{budget_id}/summary")
            summary_error = None
        except BackendError as error:
            summary, summary_error = None, error
        return render(
            request,
            "partials/budget_detail.html",
            page_title=f"Budget for {budget['trip_id']}",
            budgets=budgets,
            budget=budget,
            expenses=expenses,
            summary=summary,
            summary_error=summary_error,
            filters={
                "category": category,
                "date_from": date_from,
                "date_to": date_to,
            },
            **trip_context(budgets, budget),
        )

    @app.get("/budgets/{budget_id}/edit")
    def edit_budget(request: Request, budget_id: str) -> Response:
        try:
            budgets = list_budgets()
            budget = backend.request("GET", f"/budgets/{budget_id}")
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/budget_form.html",
            page_title="Edit budget",
            budgets=budgets,
            **trip_context(budgets),
            form=budget,
            errors={},
            action=f"/budgets/{budget_id}/edit",
            heading="Edit budget",
            budget=budget,
        )

    @app.post("/budgets/{budget_id}/edit")
    async def update_budget(request: Request, budget_id: str) -> Response:
        form = _fields(await request.form(), BUDGET_FIELDS)
        try:
            backend.request("PATCH", f"/budgets/{budget_id}", json=form)
        except BackendError as error:
            try:
                budgets = list_budgets()
            except BackendError:
                budgets = []
            return render(
                request,
                "partials/budget_form.html",
                page_title="Edit budget",
                budgets=budgets,
                form=form,
                errors=_errors_by_field(error),
                form_error=error,
                action=f"/budgets/{budget_id}/edit",
                heading="Edit budget",
                budget={"budget_id": budget_id, **form},
            )
        return RedirectResponse(f"/budgets/{budget_id}", status_code=303)

    @app.get("/budgets/{budget_id}/delete")
    def confirm_budget_delete(request: Request, budget_id: str) -> Response:
        try:
            budgets = list_budgets()
            budget = backend.request("GET", f"/budgets/{budget_id}")
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/delete_confirmation.html",
            page_title="Delete budget",
            budgets=budgets,
            title="Delete budget?",
            description=(
                f"The budget for trip {budget['trip_id']} and its view will be removed."
            ),
            action=f"/budgets/{budget_id}/delete",
            cancel_url=f"/budgets/{budget_id}",
        )

    @app.post("/budgets/{budget_id}/delete")
    def delete_budget(budget_id: str) -> Response:
        backend.request("DELETE", f"/budgets/{budget_id}")
        return RedirectResponse("/", status_code=303)

    @app.post("/budgets/{budget_id}/ai-analysis")
    async def budget_analysis(request: Request, budget_id: str) -> Response:
        form = await request.form()
        question = str(form.get("question", "")).strip()
        try:
            analysis = backend.request(
                "POST",
                f"/budgets/{budget_id}/ai-analysis",
                json={"question": question},
                timeout=settings.ai_analysis_timeout_seconds,
            )
            analysis_error = None
        except BackendError as error:
            analysis, analysis_error = None, error
        return TEMPLATES.TemplateResponse(
            request,
            "partials/ai_analysis.html",
            {
                "budget": {"budget_id": budget_id},
                "question": question,
                "analysis": analysis,
                "analysis_error": analysis_error,
            },
        )

    @app.get("/budgets/{budget_id}/expenses/new")
    def new_expense(request: Request, budget_id: str) -> Response:
        try:
            budgets = list_budgets()
            budget = backend.request("GET", f"/budgets/{budget_id}")
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/expense_form.html",
            page_title="Add expense",
            budgets=budgets,
            budget=budget,
            form={
                "trip_id": budget["trip_id"],
                "currency": budget["currency"],
                "category": "other",
            },
            errors={},
            action=f"/budgets/{budget_id}/expenses",
            heading="Add expense",
        )

    @app.post("/budgets/{budget_id}/expenses")
    async def create_expense(request: Request, budget_id: str) -> Response:
        form = _fields(await request.form(), EXPENSE_FIELDS)
        try:
            backend.request("POST", "/expenses", json=form)
        except BackendError as error:
            try:
                budgets = list_budgets()
                budget = backend.request("GET", f"/budgets/{budget_id}")
            except BackendError:
                budgets, budget = [], {"budget_id": budget_id}
            return render(
                request,
                "partials/expense_form.html",
                page_title="Add expense",
                budgets=budgets,
                budget=budget,
                form=form,
                errors=_errors_by_field(error),
                form_error=error,
                action=f"/budgets/{budget_id}/expenses",
                heading="Add expense",
            )
        return RedirectResponse(f"/budgets/{budget_id}", status_code=303)

    @app.get("/expenses/{expense_id}/edit")
    def edit_expense(request: Request, expense_id: str, budget_id: str) -> Response:
        try:
            budgets = list_budgets()
            budget = backend.request("GET", f"/budgets/{budget_id}")
            expense = backend.request("GET", f"/expenses/{expense_id}")
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/expense_form.html",
            page_title="Edit expense",
            budgets=budgets,
            budget=budget,
            form=expense,
            errors={},
            action=f"/expenses/{expense_id}/edit?budget_id={budget_id}",
            heading="Edit expense",
        )

    @app.post("/expenses/{expense_id}/edit")
    async def update_expense(
        request: Request, expense_id: str, budget_id: str
    ) -> Response:
        form = _fields(await request.form(), EXPENSE_FIELDS)
        try:
            backend.request("PATCH", f"/expenses/{expense_id}", json=form)
        except BackendError as error:
            try:
                budgets = list_budgets()
                budget = backend.request("GET", f"/budgets/{budget_id}")
            except BackendError:
                budgets, budget = [], {"budget_id": budget_id}
            return render(
                request,
                "partials/expense_form.html",
                page_title="Edit expense",
                budgets=budgets,
                budget=budget,
                form=form,
                errors=_errors_by_field(error),
                form_error=error,
                action=f"/expenses/{expense_id}/edit?budget_id={budget_id}",
                heading="Edit expense",
            )
        return RedirectResponse(f"/budgets/{budget_id}", status_code=303)

    @app.get("/expenses/{expense_id}/delete")
    def confirm_expense_delete(
        request: Request, expense_id: str, budget_id: str
    ) -> Response:
        try:
            budgets = list_budgets()
            expense = backend.request("GET", f"/expenses/{expense_id}")
        except BackendError as error:
            return error_page(request, error)
        return render(
            request,
            "partials/delete_confirmation.html",
            page_title="Delete expense",
            budgets=budgets,
            title="Delete expense?",
            description=(
                f"{expense['description']} ({expense['currency']} "
                f"{expense['amount']}) will be permanently removed."
            ),
            action=f"/expenses/{expense_id}/delete?budget_id={budget_id}",
            cancel_url=f"/budgets/{budget_id}",
        )

    @app.post("/expenses/{expense_id}/delete")
    def delete_expense(expense_id: str, budget_id: str) -> Response:
        backend.request("DELETE", f"/expenses/{expense_id}")
        return RedirectResponse(f"/budgets/{budget_id}", status_code=303)

    return app


app = create_app()
