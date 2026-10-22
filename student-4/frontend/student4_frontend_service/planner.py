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
from .planner_selection import Selection, scheduling_body

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


async def render(
    request: Request,
    result: PlannerResponse | None = None,
    *,
    error: str | None = None,
    run_id: str | None = None,
    submitted: ReviewForm | None = None,
    selection: Selection | None = None,
    recovering: bool | None = None,
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
    selection = selection or Selection.from_fields(request.query_params)
    trips = []
    trip_error = None
    displayed_answer = result.answer if result else None
    dismiss_urls: dict[str, str] = {}
    if result is not None:
        selection.resolve(result)
        if result.run.status == "awaiting_human" and result.answer.activities:
            try:
                directory = await _client(request).trips()
                trips = directory.trips
                if not directory.available:
                    trip_error = (
                        "Trips are unavailable. Refresh before approving activities."
                    )
            except FrontendError as exc:
                trip_error = exc.detail
        if result.run.status == "awaiting_human":
            dismiss_urls = {
                key: selection.url(result.run.run_id, without=key)
                for key in selection.ids
            }
            # The original narrative may reference dismissed suggestions.
            if set(selection.ids) != set(result.answer.activities):
                displayed_answer = result.answer.model_copy(
                    update={
                        "parts": [
                            part
                            for part in result.answer.parts
                            if part.type == "activity"
                            and str(part.activity_id) in selection.ids
                        ],
                        "activities": {
                            key: value
                            for key, value in result.answer.activities.items()
                            if key in selection.ids
                        },
                    }
                )
        if submitted is None and review_form is not None:
            review_form.activity_ids = list(selection.ids)
    return templates.TemplateResponse(
        request,
        partial if request.headers.get("HX-Request") == "true" else "planner_page.html",
        {
            "planner": result,
            "displayed_answer": displayed_answer,
            "selection": selection,
            "selection_url": selection.url(result.run.run_id) if result else "",
            "dismiss_urls": dismiss_urls,
            "trips": trips,
            "trip_error": trip_error,
            "error": error,
            "run_id": result.run.run_id if result else run_id,
            "review_form": review_form,
            "recovering": submitted is not None if recovering is None else recovering,
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
        return await render(request, result)
    except FrontendError as exc:
        return await render(request, error=exc.detail)


@router.get("/planner/{run_id}")
async def get(request: Request, run_id: RunId, client: ClientDep) -> Response:
    try:
        return await render(request, await client.planner(run_id))
    except FrontendError as exc:
        return await render(request, error=exc.detail, run_id=run_id)


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
    if decision in {"approve", "correct"} and str(form.get("selection", "")) == "1":
        selected = [str(UUID(str(value))) for value in form.getlist("selected_ids")]
        if decision == "correct":
            selected = [str(UUID(str(value))) for value in form.getlist("activity_ids")]
        body.update(scheduling_body(form, list(dict.fromkeys(selected))))
    return body


@router.post("/planner/{run_id}/review")
async def review(request: Request, run_id: RunId, client: ClientDep) -> Response:
    form = await request.form()
    try:
        body = decision_body(form)
        return await render(request, await client.review_planner(run_id, body))
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
    return await render(
        request,
        result,
        error=error,
        run_id=run_id,
        submitted=ReviewForm.from_form(form),
        selection=Selection.from_fields(form),
    )


@router.post("/planner/{run_id}/selection")
async def select(request: Request, run_id: RunId, client: ClientDep) -> Response:
    """Change presentation only, preserving edits without sending a decision."""
    form = await request.form()
    try:
        result = await client.planner(run_id)
    except FrontendError as exc:
        return await recover_review(request, run_id, client, form, error=exc.detail)
    selection = Selection.from_fields(form)
    selection.resolve(result)
    submitted = ReviewForm.from_form(form)
    if result.run.status == "awaiting_human":
        if str(form.get("restore", "")) == "all":
            selection.ids = list(result.answer.activities)
            submitted.activity_ids = list(selection.ids)
        else:
            dismissed = str(form.get("dismiss_id", ""))
            selection.ids = [key for key in selection.ids if key != dismissed]
            submitted.activity_ids = [
                key for key in submitted.activity_ids if key != dismissed
            ]
        selection.explicit = True
    response = await render(
        request,
        result,
        selection=selection,
        submitted=submitted,
        recovering=False,
    )
    response.headers["HX-Push-Url"] = selection.url(run_id)
    return response


@router.post("/planner/{run_id}/regenerate")
async def regenerate(request: Request, run_id: RunId, client: ClientDep) -> Response:
    form = await request.form()
    reviewer = str(form.get("reviewer", "")).strip()
    feedback = str(form.get("feedback", "")).strip()
    try:
        if not 1 <= len(reviewer) <= 60 or not 1 <= len(feedback) <= 1000:
            msg = "Enter your name and feedback (1-1000 characters) to regenerate."
            raise ValueError(msg)
        dismissed = [str(UUID(str(value))) for value in form.getlist("dismissed_ids")]
        result = await client.regenerate_planner(
            run_id,
            {
                "reviewer": reviewer,
                "feedback": feedback,
                "dismissed_activity_ids": list(dict.fromkeys(dismissed)),
            },
        )
        return await render(request, result)
    except (ValueError, FrontendError) as exc:
        message = exc.detail if isinstance(exc, FrontendError) else str(exc)
        return await recover_review(request, run_id, client, form, error=message)


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
        return await render(request, error=exc.detail, run_id=run_id)
