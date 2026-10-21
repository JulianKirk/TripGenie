"""Smart Planner HTML flow; all requests go through Student 4's backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response

from .client import BackendClient
from .errors import FrontendError
from .planner_models import RunId  # noqa: TC001 - FastAPI annotation

if TYPE_CHECKING:
    from fastapi.templating import Jinja2Templates
    from starlette.datastructures import FormData

    from .planner_models import PlannerResponse

router = APIRouter()


def _client(request: Request) -> BackendClient:
    return cast("BackendClient", request.app.state.backend_client)


ClientDep = Annotated[BackendClient, Depends(_client)]


def render(
    request: Request,
    result: PlannerResponse | None = None,
    *,
    error: str | None = None,
    run_id: str | None = None,
) -> Response:
    templates = cast("Jinja2Templates", request.app.state.templates)
    partial = "partials/planner_results.html"
    return templates.TemplateResponse(
        request,
        partial if request.headers.get("HX-Request") == "true" else "planner_page.html",
        {
            "planner": result,
            "error": error,
            "run_id": run_id,
            "results_template": partial,
        },
    )


async def start(request: Request, client: BackendClient, form: FormData) -> Response:
    body: dict[str, object] = {"question": str(form.get("question", "")).strip()}
    trip = str(form.get("trip_id", "")).strip()
    if trip:
        body["trip_id"] = trip
    try:
        result = await client.start_planner(body)
        return render(request, result)
    except FrontendError as exc:
        return render(request, error=exc.detail)


@router.get("/planner/{run_id}")
async def get(request: Request, run_id: RunId, client: ClientDep) -> Response:
    try:
        return render(request, await client.planner(run_id))
    except FrontendError as exc:
        return render(request, error=exc.detail, run_id=run_id)


def decision_body(form: FormData) -> dict[str, object]:
    decision = str(form.get("decision", ""))
    reviewer = str(form.get("reviewer", "")).strip()
    notes = str(form.get("notes", "")).strip()
    if (
        decision not in {"approve", "correct", "reject"}
        or not 1 <= len(reviewer) <= 60
        or len(notes) > 1000
    ):
        msg = (
            "Choose a decision and enter your name (up to 60 characters); "
            "notes must be at most 1000 characters."
        )
        raise ValueError(msg)
    body: dict[str, object] = {
        "decision": decision,
        "reviewer": reviewer,
        "notes": notes or None,
    }
    if decision == "correct":
        text = str(form.get("correction", "")).strip()
        if not 1 <= len(text) <= 1000:
            msg = "Enter corrected recommendation text (1-1000 characters)."
            raise ValueError(msg)
        ids = list(
            dict.fromkeys(
                str(UUID(str(value))) for value in form.getlist("activity_ids")
            )
        )
        if len(ids) > 6:
            msg = "Keep at most six activities."
            raise ValueError(msg)
        parts = [
            {"type": "text", "text": text},
            *[{"type": "activity", "activity_id": key} for key in ids],
        ]
        body["corrected_result"] = {"type": "final", "parts": parts}
    return body


@router.post("/planner/{run_id}/review")
async def review(request: Request, run_id: RunId, client: ClientDep) -> Response:
    form = await request.form()
    try:
        body = decision_body(form)
        return render(request, await client.review_planner(run_id, body))
    except (ValueError, FrontendError) as exc:
        message = exc.detail if isinstance(exc, FrontendError) else str(exc)
        return render(request, error=message, run_id=run_id)


@router.get("/planner/{run_id}/history")
async def history(request: Request, run_id: RunId, client: ClientDep) -> Response:
    try:
        evidence = await client.planner_history(run_id)
        return JSONResponse(
            evidence.model_dump(mode="json"),
            headers={"Content-Disposition": f'attachment; filename="{run_id}.json"'},
        )
    except FrontendError as exc:
        return render(request, error=exc.detail, run_id=run_id)
