"""Inline Smart Planner with staged card choices and a single approval gate."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response

from .catalogue import catalogue_context
from .client import BackendClient
from .errors import FrontendError
from .planner_choices import Choices
from .planner_models import RunId  # noqa: TC001 - FastAPI resolves annotations.
from .planner_presentation import presentation

if TYPE_CHECKING:
    from fastapi.templating import Jinja2Templates
    from starlette.datastructures import FormData

    from .planner_models import PlannerResponse

router = APIRouter()


def _client(request: Request) -> BackendClient:
    return cast("BackendClient", request.app.state.backend_client)


ClientDep = Annotated[BackendClient, Depends(_client)]


async def render(
    request: Request,
    result: PlannerResponse | None = None,
    *,
    error: str | None = None,
    run_id: str | None = None,
    choices: Choices | None = None,
    reason_id: str = "",
) -> Response:
    templates = cast("Jinja2Templates", request.app.state.templates)
    state = choices or Choices()
    trips = []
    trip_error = None
    if result and result.run.status == "awaiting_human" and result.answer.activities:
        try:
            directory = await _client(request).trips()
            trips = directory.trips
            if not directory.available:
                trip_error = "Trips are unavailable. You can still review suggestions."
        except FrontendError as exc:
            trip_error = exc.detail
    context: dict[str, object] = {
        "planner_mode": True,
        "planner": result,
        "error": error,
        "run_id": result.run.run_id if result else run_id,
        "trips": trips,
        "trip_error": trip_error,
        "choices": state,
        "reason_id": reason_id,
    }
    if result:
        ids = state.resolve(result)
        context.update(presentation(result))
        context["suggestion_ids"] = ids
        context["approved_count"] = sum(
            value == "approve" for value in state.decisions.values()
        )
    partial = request.headers.get("HX-Request", "").lower() == "true"
    if not partial:
        catalogue = await catalogue_context(request, _client(request))
        catalogue["catalogue_error"] = catalogue.pop("error", None)
        context = {**catalogue, **context}
    response = templates.TemplateResponse(
        request, "partials/planner_results.html" if partial else "page.html", context
    )
    if result and partial:
        response.headers["HX-Replace-Url"] = (
            f"/?planner_run={result.run.run_id}#ai-suggestions"
        )
    return response


async def start(request: Request, client: BackendClient, form: FormData) -> Response:
    body: dict[str, object] = {"question": str(form.get("question", "")).strip()}
    if trip := str(form.get("trip_id", "")).strip():
        body["trip_id"] = trip
    try:
        return await render(request, await client.start_planner(body))
    except FrontendError as exc:
        return await render(request, error=exc.detail)


@router.get("/planner/{run_id}")
async def get(request: Request, run_id: RunId, client: ClientDep) -> Response:
    try:
        return await render(request, await client.planner(run_id))
    except FrontendError as exc:
        return await render(request, error=exc.detail, run_id=run_id)


@router.post("/planner/{run_id}/choices")
async def choose(request: Request, run_id: RunId, client: ClientDep) -> Response:
    form = await request.form()
    state = Choices.from_form(form)
    try:
        result = await client.planner(run_id)
    except FrontendError as exc:
        return await render(request, error=exc.detail, run_id=run_id, choices=state)
    ids = state.resolve(result)
    error = None
    reason_id = ""
    if result.run.status == "awaiting_human":
        for field, decision in (
            ("approve_id", "approve"),
            ("reject_id", "reject"),
            ("reject_reason_id", "reject"),
        ):
            if key := str(form.get(field, "")):
                if key not in ids:
                    error = "Choose an activity from this result."
                elif field == "reject_reason_id" and not state.reasons.get(key):
                    error = "Enter a reason to reject this suggestion."
                    reason_id = key
                else:
                    state.decisions[key] = decision
                    if field != "reject_reason_id":
                        state.reasons.pop(key, None)
                break
    return await render(
        request, result, choices=state, error=error, reason_id=reason_id
    )


@router.post("/planner/{run_id}/review")
async def review(request: Request, run_id: RunId, client: ClientDep) -> Response:
    state = Choices.from_form(await request.form())
    result = None
    try:
        result = await client.planner(run_id)
        ids = state.resolve(result)
        body = state.body(ids)
        updated = await client.review_planner(run_id, body)
        return await render(request, updated, choices=state)
    except (ValueError, FrontendError) as exc:
        error = exc.detail if isinstance(exc, FrontendError) else str(exc)
        # Read the authoritative run after an uncertain acknowledgement; never replay.
        try:
            result = await client.planner(run_id)
        except FrontendError:
            result = None
        return await render(request, result, error=error, run_id=run_id, choices=state)


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
