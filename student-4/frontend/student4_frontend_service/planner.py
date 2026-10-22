"""Inline Smart Planner with staged card choices and a single approval gate."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response

from .catalogue import catalogue_context
from .client import BackendClient
from .errors import FrontendError
from .models import ItinerarySelectionWrite
from .planner_choices import Choices
from .planner_models import RunId  # noqa: TC001 - FastAPI resolves annotations.
from .planner_presentation import presentation

if TYPE_CHECKING:
    from fastapi.templating import Jinja2Templates
    from starlette.datastructures import FormData

    from .models import TripOption
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
    dialog: dict[str, object] | None = None,
    close_dialog: bool = False,
) -> Response:
    templates = cast("Jinja2Templates", request.app.state.templates)
    state = choices or Choices()
    trips = []
    trip_error = None
    if result and result.answer.activities:
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
        "dialog": dialog,
        "close_dialog": close_dialog,
        "trip_names": {trip.id: trip.name for trip in trips},
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


def _approval_schedule(state: Choices, key: str, trips: list[TripOption]) -> None:
    if not state.dates.get(key) or not state.times.get(key):
        msg = "Choose a date and start time for this activity."
        raise ValueError(msg)
    trip_id = state.trip_ids.get(key) or state.trip_id
    trip = next((row for row in trips if row.id == trip_id), None)
    if trip is None:
        msg = "Choose an available itinerary for this activity."
        raise ValueError(msg)
    schedule = ItinerarySelectionWrite.model_validate(
        {"date": state.dates[key], "start_time": state.times[key]}
    )
    if schedule.date is None or not trip.start_date <= schedule.date <= trip.end_date:
        msg = "Choose a date within the selected itinerary dates."
        raise ValueError(msg)
    state.trip_ids[key] = trip.id


async def _dialog_response(
    request: Request,
    result: PlannerResponse,
    state: Choices,
    key: str,
    kind: Literal["approve", "reject"],
    *,
    error: str | None = None,
) -> Response:
    templates = cast("Jinja2Templates", request.app.state.templates)
    trips = []
    if kind == "approve":
        try:
            directory = await _client(request).trips()
            trips = directory.trips
            if not directory.available:
                error = "Itineraries are temporarily unavailable."
        except FrontendError as exc:
            error = exc.detail
    context: dict[str, object] = {
        "planner": result,
        "run": result.run,
        "choices": state,
        "dialog_key": key,
        "dialog_kind": kind,
        "dialog_error": error,
        "dialog_trips": trips,
    }
    if request.headers.get("HX-Request", "").lower() == "true":
        return templates.TemplateResponse(
            request,
            "partials/planner_dialog.html",
            context,
            headers={"HX-Retarget": "#activity-dialog", "HX-Reswap": "innerHTML"},
        )
    return await render(request, result, choices=state, dialog=context)


@router.post("/planner/{run_id}/dialog")
async def open_dialog(request: Request, run_id: RunId, client: ClientDep) -> Response:
    form = await request.form()
    state = Choices.from_form(form)
    try:
        result = await client.planner(run_id)
        ids = state.resolve(result)
        if form.get("cancel"):
            return await render(request, result, choices=state, close_dialog=True)
        kind: Literal["approve", "reject"] = (
            "approve" if form.get("dialog_approve") else "reject"
        )
        key = str(form.get(f"dialog_{kind}", ""))
        if result.run.status != "awaiting_human" or key not in ids:
            msg = "This suggestion is no longer awaiting review."
            raise ValueError(msg)
        if kind == "approve":
            activity = result.answer.activities.get(key)
            if (
                activity is None
                or not activity.is_active
                or any(
                    check.blocking and not check.passed for check in result.run.checks
                )
            ):
                msg = "This suggestion cannot be approved."
                raise ValueError(msg)
        return await _dialog_response(request, result, state, key, kind)
    except (ValueError, FrontendError) as exc:
        message = exc.detail if isinstance(exc, FrontendError) else str(exc)
        response = await render(request, error=message, run_id=run_id, choices=state)
        response.headers.update(
            {"HX-Retarget": "#planner-result", "HX-Reswap": "outerHTML"}
        )
        return response


@router.post("/planner/{run_id}/choices")
async def choose(request: Request, run_id: RunId, client: ClientDep) -> Response:
    form = await request.form()
    state = Choices.from_form(form)
    result = None
    key = str(
        form.get("approve_id")
        or form.get("reject_id")
        or form.get("reject_reason_id")
        or ""
    )
    kind: Literal["approve", "reject"] = (
        "approve" if form.get("approve_id") else "reject"
    )
    try:
        result = await client.planner(run_id)
        ids = state.resolve(result)
        if result.run.status != "awaiting_human" or key not in ids:
            msg = "Choose an activity from this result that is awaiting review."
            raise ValueError(msg)
        if kind == "approve":
            activity = result.answer.activities.get(key)
            if (
                activity is None
                or not activity.is_active
                or any(
                    check.blocking and not check.passed for check in result.run.checks
                )
            ):
                msg = "This suggestion cannot be approved."
                raise ValueError(msg)
            directory = await client.trips()
            _approval_schedule(
                state, key, directory.trips if directory.available else []
            )
            state.reasons.pop(key, None)
        elif len(state.reasons.get(key, "")) > 1000:
            msg = "Keep the rejection reason within 1000 characters."
            raise ValueError(msg)
        state.decisions[key] = kind
        return await render(request, result, choices=state, close_dialog=True)
    except (ValueError, FrontendError) as exc:
        message = exc.detail if isinstance(exc, FrontendError) else str(exc)
        if result and key in result.answer.activities:
            return await _dialog_response(
                request, result, state, key, kind, error=message
            )
        return await render(
            request, result, error=message, run_id=run_id, choices=state
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
