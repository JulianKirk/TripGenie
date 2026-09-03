from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast
from uuid import UUID  # noqa: TC003 - FastAPI resolves route annotations at runtime.

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.datastructures import FormData
from starlette.responses import RedirectResponse, Response

from .client import BackendClient
from .config import Settings
from .errors import FrontendError
from .forms import activity_form_values, parse_activity_form, submitted_form_values
from .models import ItinerarySelectionWrite
from .presenters import (
    accessibility_label,
    format_duration,
    format_location,
    format_money,
    group_schedules,
    party_total,
)
from .query import QueryInputError, build_search_body

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import httpx

    from .models import ActivityPage, CategoryList

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
TEMPLATES.env.filters.update(
    money=format_money,
    duration=format_duration,
    location=format_location,
    accessibility=accessibility_label,
)
TEMPLATES.env.globals["party_total"] = party_total


def _client(request: Request) -> BackendClient:
    return cast("BackendClient", request.app.state.backend_client)


ClientDep = Annotated[BackendClient, Depends(_client)]


def _error(exc: BaseException, fallback: str) -> str:
    return exc.detail if isinstance(exc, FrontendError) else fallback


def _category_labels(categories: CategoryList | BaseException) -> dict[str, str]:
    if isinstance(categories, BaseException):
        return {}
    return {row.code: row.label for row in categories.categories}


def _results_context(
    *,
    page: object,
    labels: dict[str, str],
    params: object,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "page": page if not isinstance(page, BaseException) else None,
        "labels": labels,
        "params": params,
        "error": error,
        "party_size": getattr(params, "get", lambda _name: None)("party_size"),
    }


def _validation_errors(exc: ValidationError) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for item in exc.errors(include_url=False, include_context=False):
        field = ".".join(str(part) for part in item["loc"])
        errors.setdefault(field, []).append(str(item["msg"]))
    return errors


def _redirect(activity_id: UUID | None = None) -> RedirectResponse:
    suffix = f"#activity-{activity_id}" if activity_id else ""
    return RedirectResponse(f"/{suffix}", status_code=303)


async def _form_response(
    request: Request,
    client: BackendClient,
    *,
    activity_id: UUID | None,
) -> Any:
    form = await request.form()
    assert isinstance(form, FormData)
    values = submitted_form_values(form)
    try:
        write = parse_activity_form(form)
    except ValidationError as exc:
        return await _render_activity_form(
            request,
            client,
            activity_id=activity_id,
            values=values,
            errors=_validation_errors(exc),
        )
    try:
        activity = (
            await client.create_activity(write)
            if activity_id is None
            else await client.replace_activity(activity_id, write)
        )
    except FrontendError as exc:
        return await _render_activity_form(
            request,
            client,
            activity_id=activity_id,
            values=values,
            errors={"general": [exc.detail]},
        )
    if request.headers.get("HX-Request", "").lower() == "true":
        return Response(
            status_code=204,
            headers={"HX-Refresh": "true"},
        )
    return _redirect(activity.id)


async def _render_activity_form(
    request: Request,
    client: BackendClient,
    *,
    activity_id: UUID | None,
    values: dict[str, object],
    errors: dict[str, list[str]],
) -> Any:
    try:
        categories = await client.categories()
    except FrontendError as exc:
        errors.setdefault("general", []).append(exc.detail)
        categories = None
    if not values.get("availability_schedules"):
        values["availability_schedules"] = [
            {"recurring_weekly": "true", "day_of_week": "MONDAY"}
        ]
    return TEMPLATES.TemplateResponse(
        request,
        "partials/activity_form.html",
        {
            "activity_id": activity_id,
            "values": values,
            "errors": errors,
            "categories": categories,
        },
    )


router = APIRouter()


@router.get("/health")
async def health(request: Request, client: ClientDep) -> dict[str, str]:
    try:
        backend = await client.health()
    except FrontendError:
        status = "unavailable"
    else:
        status = backend.status
    return {
        "status": "ok" if status == "ok" else "degraded",
        "service": request.app.state.settings.service_name,
        "backend": status,
    }


@router.get("/")
async def index(request: Request, client: ClientDep) -> Any:
    try:
        body = build_search_body(request.query_params)
    except QueryInputError as exc:
        body = {"limit": 20, "offset": 0}
        query_error: str | None = str(exc)
    else:
        query_error = None
    body["include_inactive"] = True
    categories, page = await asyncio.gather(
        client.categories(), client.search(body), return_exceptions=True
    )
    labels = _category_labels(categories)
    results_error = query_error
    if isinstance(page, BaseException):
        results_error = _error(page, "Activities could not be loaded.")
    context = {
        "categories": None if isinstance(categories, BaseException) else categories,
        "selected_limit": body["limit"],
        "categories_error": (
            _error(categories, "Categories could not be loaded.")
            if isinstance(categories, BaseException)
            else None
        ),
        **_results_context(
            page=page,
            labels=labels,
            params=request.query_params,
            error=results_error,
        ),
    }
    return TEMPLATES.TemplateResponse(request, "page.html", context)


@router.get("/activity")
async def results(request: Request, client: ClientDep) -> Any:
    try:
        body = build_search_body(request.query_params)
    except QueryInputError as exc:
        context = _results_context(
            page=exc,
            labels={},
            params=request.query_params,
            error=_error(exc, str(exc)),
        )
    else:
        body["include_inactive"] = True
        categories, page = await asyncio.gather(
            client.categories(), client.search(body), return_exceptions=True
        )
        context = _results_context(
            page=page,
            labels=_category_labels(categories),
            params=request.query_params,
            error=(
                _error(page, "Activities could not be loaded.")
                if isinstance(page, BaseException)
                else None
            ),
        )
    return TEMPLATES.TemplateResponse(request, "partials/results.html", context)


@router.get("/activity/{activity_id}")
async def detail(request: Request, activity_id: UUID, client: ClientDep) -> Any:
    activity, categories = await asyncio.gather(
        client.activity(activity_id), client.categories(), return_exceptions=True
    )
    if isinstance(activity, BaseException):
        return TEMPLATES.TemplateResponse(
            request,
            "partials/error_state.html",
            {
                "error": _error(activity, "Activity details could not be loaded."),
                "dialog": True,
            },
        )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/activity_detail.html",
        {
            "activity": activity,
            "labels": _category_labels(categories),
            "schedules": group_schedules(activity.availability_schedules),
        },
    )


def _picker_response(
    request: Request,
    *,
    activity_id: UUID,
    is_active: bool = True,
    picker: object | None = None,
    error: str | None = None,
) -> Any:
    return TEMPLATES.TemplateResponse(
        request,
        "partials/itinerary_picker.html",
        {
            "activity_id": activity_id,
            "is_active": is_active,
            "picker": picker,
            "error": error,
        },
    )


@router.get("/activity/{activity_id}/itineraries")
async def itinerary_picker(
    request: Request,
    activity_id: UUID,
    client: ClientDep,
) -> Any:
    try:
        activity, picker = await asyncio.gather(
            client.activity(activity_id), client.itineraries(activity_id)
        )
    except FrontendError as exc:
        return _picker_response(request, activity_id=activity_id, error=exc.detail)
    return _picker_response(
        request,
        activity_id=activity_id,
        is_active=activity.is_active,
        picker=picker,
    )


@router.get("/activity/{activity_id}/itineraries/dialog")
async def itinerary_dialog(
    request: Request,
    activity_id: UUID,
    client: ClientDep,
) -> Any:
    try:
        activity, picker = await asyncio.gather(
            client.activity(activity_id), client.itineraries(activity_id)
        )
    except FrontendError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/itinerary_dialog.html",
            {
                "activity_id": activity_id,
                "activity_name": "activity",
                "is_active": True,
                "picker": None,
                "error": exc.detail,
            },
        )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/itinerary_dialog.html",
        {
            "activity_id": activity_id,
            "activity_name": activity.name,
            "is_active": activity.is_active,
            "picker": picker,
            "error": None,
        },
    )


async def _itinerary_write(request: Request) -> ItinerarySelectionWrite:
    form = await request.form()
    date = str(form.get("date", "")).strip()
    start_time = str(form.get("start_time", "")).strip()
    payload = {}
    if date:
        payload["date"] = date
    if start_time:
        payload["start_time"] = start_time
    return ItinerarySelectionWrite.model_validate(payload)


@router.put("/activity/{activity_id}/itineraries/{trip_id}")
@router.post("/activity/{activity_id}/itineraries/{trip_id}")
async def put_itinerary(
    request: Request,
    activity_id: UUID,
    trip_id: str,
    client: ClientDep,
) -> Any:
    try:
        activity = await client.activity(activity_id)
        if not activity.is_active:
            current = await client.itineraries(activity_id)
            selected = next(
                (
                    row
                    for row in current.itineraries
                    if row.itinerary_id == trip_id and row.selected
                ),
                None,
            )
            if selected is None:
                return _picker_response(
                    request,
                    activity_id=activity_id,
                    is_active=False,
                    error="This activity is inactive and cannot be added.",
                )
        write = await _itinerary_write(request)
        picker = await client.put_itinerary(activity_id, trip_id, write)
    except (FrontendError, ValidationError) as exc:
        error = (
            exc.detail
            if isinstance(exc, FrontendError)
            else "Enter a valid date and local time."
        )
        return _picker_response(request, activity_id=activity_id, error=error)
    return _picker_response(
        request,
        activity_id=activity_id,
        is_active=activity.is_active,
        picker=picker,
    )


@router.delete("/activity/{activity_id}/itineraries/{trip_id}")
@router.post("/activity/{activity_id}/itineraries/{trip_id}/remove")
async def remove_itinerary(
    request: Request,
    activity_id: UUID,
    trip_id: str,
    client: ClientDep,
) -> Any:
    try:
        activity = await client.activity(activity_id)
        picker = await client.delete_itinerary(activity_id, trip_id)
    except FrontendError as exc:
        return _picker_response(request, activity_id=activity_id, error=exc.detail)
    return _picker_response(
        request,
        activity_id=activity_id,
        is_active=activity.is_active,
        picker=picker,
    )


@router.get("/manage")
async def manage(request: Request, client: ClientDep) -> Any:
    try:
        body = build_search_body(request.query_params)
    except QueryInputError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "manage.html",
            {"page": None, "labels": {}, "error": str(exc)},
        )
    body["include_inactive"] = True
    page: ActivityPage | None
    categories: CategoryList | None
    error: str | None
    page_result, categories_result = await asyncio.gather(
        client.search(body), client.categories(), return_exceptions=True
    )
    if isinstance(page_result, BaseException):
        page = None
        error = _error(page_result, "Activities could not be loaded.")
    else:
        page = page_result
        error = None
    categories = (
        None if isinstance(categories_result, BaseException) else categories_result
    )
    return TEMPLATES.TemplateResponse(
        request,
        "manage.html",
        {
            "page": page,
            "labels": _category_labels(categories) if categories else {},
            "error": error,
        },
    )


@router.get("/manage/activity/new")
async def new_activity(request: Request, client: ClientDep) -> Any:
    return await _render_activity_form(
        request, client, activity_id=None, values={}, errors={}
    )


@router.post("/manage/activity")
async def create_activity(request: Request, client: ClientDep) -> Any:
    return await _form_response(request, client, activity_id=None)


@router.get("/manage/activity/{activity_id}/edit")
async def edit_activity(
    request: Request,
    activity_id: UUID,
    client: ClientDep,
) -> Any:
    try:
        activity = await client.activity(activity_id)
    except FrontendError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/error_state.html",
            {"error": exc.detail, "dialog": True},
        )
    return await _render_activity_form(
        request,
        client,
        activity_id=activity_id,
        values=activity_form_values(activity),
        errors={},
    )


@router.put("/manage/activity/{activity_id}")
@router.post("/manage/activity/{activity_id}")
async def replace_activity(
    request: Request,
    activity_id: UUID,
    client: ClientDep,
) -> Any:
    return await _form_response(request, client, activity_id=activity_id)


@router.get("/manage/activity/{activity_id}/delete")
async def delete_confirmation(
    request: Request,
    activity_id: UUID,
    client: ClientDep,
) -> Any:
    try:
        activity = await client.activity(activity_id)
    except FrontendError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/error_state.html",
            {"error": exc.detail, "dialog": True},
        )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/delete_confirmation.html",
        {"activity": activity},
    )


@router.delete("/manage/activity/{activity_id}")
@router.post("/manage/activity/{activity_id}/delete")
async def delete_activity(
    request: Request,
    activity_id: UUID,
    client: ClientDep,
) -> Any:
    try:
        await client.delete_activity(activity_id)
    except FrontendError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "partials/error_state.html",
            {"error": exc.detail, "dialog": True},
        )
    if request.headers.get("HX-Request", "").lower() == "true":
        return Response(status_code=204, headers={"HX-Redirect": "/"})
    return _redirect()


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    service_settings = settings or Settings.from_env()
    backend_client = BackendClient(service_settings, transport=transport)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        await application.state.backend_client.close()

    application = FastAPI(title="TripGenie Student 4 Frontend", lifespan=lifespan)
    application.state.settings = service_settings
    application.state.backend_client = backend_client
    application.mount(
        "/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static"
    )
    application.include_router(router)
    return application


app = create_app()
