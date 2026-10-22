"""Smart Planner HTML flow; all requests go through Student 4's backend."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class ReviewForm:
    reviewer: str
    notes: str
    corrections: list[str]
    activity_ids: list[str]

    @classmethod
    def from_form(cls, form: FormData) -> ReviewForm:
        return cls(
            reviewer=str(form.get("reviewer", "")),
            notes=str(form.get("notes", "")),
            corrections=[str(value) for value in form.getlist("correction")] or [""],
            activity_ids=[str(value) for value in form.getlist("activity_ids")],
        )


def render(
    request: Request,
    result: PlannerResponse | None = None,
    *,
    error: str | None = None,
    run_id: str | None = None,
    submitted: ReviewForm | None = None,
) -> Response:
    templates = cast("Jinja2Templates", request.app.state.templates)
    partial = "partials/planner_results.html"
    review_form = submitted
    if review_form is None and result is not None:
        review_form = ReviewForm(
            reviewer="",
            notes="",
            corrections=[
                part.text for part in result.answer.parts if part.type == "text"
            ]
            or [""],
            activity_ids=list(result.answer.activities),
        )
    return templates.TemplateResponse(
        request,
        partial if request.headers.get("HX-Request") == "true" else "planner_page.html",
        {
            "planner": result,
            "error": error,
            "run_id": result.run.run_id if result else run_id,
            "review_form": review_form,
            "recovering": submitted is not None,
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
        texts = [
            text for value in form.getlist("correction") if (text := str(value).strip())
        ]
        if not texts or any(not 1 <= len(text) <= 1000 for text in texts):
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
            *[{"type": "text", "text": text} for text in texts],
            *[{"type": "activity", "activity_id": key} for key in ids],
        ]
        if len(parts) > 12:
            msg = "Keep at most twelve recommendation parts, including activities."
            raise ValueError(msg)
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
        return await recover_review(request, run_id, client, form, error=message)


async def recover_review(
    request: Request,
    run_id: str,
    client: BackendClient,
    form: FormData,
    *,
    error: str | None = None,
) -> Response:
    result = None
    try:
        result = await client.planner(run_id)
    except FrontendError as exc:
        error = f"{error} {exc.detail}" if error else exc.detail
    return render(
        request,
        result,
        error=error,
        run_id=run_id,
        submitted=ReviewForm.from_form(form),
    )


@router.post("/planner/{run_id}/recover")
async def recover(request: Request, run_id: RunId, client: ClientDep) -> Response:
    """Refresh authoritative status while retaining edits; never submit a decision."""
    return await recover_review(request, run_id, client, await request.form())


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
