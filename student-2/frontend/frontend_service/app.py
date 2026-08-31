"""The accommodation webpage.

HTMX swaps HTML fragments, and the backend service speaks JSON, so this service
is what turns one into the other. It also exists because the only filtered
search the backend offers is `QUERY /accommodation` with a JSON body, and HTMX
can issue GET/POST/PUT/PATCH/DELETE and nothing else -- the filter form arrives
here as query parameters and leaves as that body.

See ../../docs/backend-service-api.md for the contract this consumes.

ponytail: no pydantic mirror of the accommodation message, no client module.
The decoded JSON goes straight into the templates. Add models here when this
service starts computing on the data rather than displaying it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from frontend_service.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.datastructures import QueryParams

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))

PATH = "/accommodation"
UNREACHABLE = "The accommodation service is not responding. Try again shortly."

# The filter form's inputs, grouped by where they sit in the QUERY body. The
# name on the left is the form field; the name on the right is the message
# field. Adding a filter is a line here and an input in the template.
MATCH_FIELDS = {
    "name": "name",
    "description": "description",
    "type": "type",
    "availability_status": "availability_status",
}
LOCATION_FIELDS = {
    "country": "country",
    "city": "city",
    "street": "street",
    "street_number": "street_number",
}
ROOM_FIELDS = {
    "room_count": "room_count",
    "bed_count": "bed_count",
    "room_description": "description",
}
BOUND_FIELDS = (
    "price_min",
    "price_max",
    "rating_min",
    "rating_max",
    "room_count_min",
    "bed_count_min",
)
PAGE_SIZES = (10, 20, 50, 100)
DEFAULT_LIMIT = 20


class BackendError(Exception):
    """The backend could not answer. Carries what to show the user."""


def _picked(params: QueryParams, fields: dict[str, str]) -> dict[str, Any]:
    """The fields the user actually filled in. A blank input is not a filter --
    it has to be dropped rather than sent, or an empty search box would ask for
    accommodations whose name is the empty string."""
    return {
        message_field: params[form_field].strip()
        for form_field, message_field in fields.items()
        if params.get(form_field, "").strip()
    }


def query_body(params: QueryParams) -> dict[str, Any]:
    """The filter form, as the QUERY body documented in backend-service-api.md."""
    match: dict[str, Any] = _picked(params, MATCH_FIELDS)
    amenities = [value for value in params.getlist("amenities") if value.strip()]
    if amenities:
        match["amenities"] = amenities

    location = _picked(params, LOCATION_FIELDS)
    # The backend rejects a city without a country ("Sydney" is ambiguous), so
    # an unpaired city is dropped here rather than sent for a 400. The template
    # keeps the city input disabled until a country is chosen, so a user of the
    # page cannot get here anyway.
    if "country" not in location:
        location.pop("city", None)
    if location:
        match["location_details"] = location

    room = _picked(params, ROOM_FIELDS)
    if room:
        match["room_details"] = room

    body: dict[str, Any] = {"accommodation": match}
    for field in BOUND_FIELDS:
        value = params.get(field, "").strip()
        if value:
            body[field] = value
    # Paging comes off the URL, so it is coerced and clamped here rather than
    # forwarded: a hand-edited `?limit=abc` should be a first page, not a 400,
    # and the pager arithmetic below needs real integers either way.
    body["limit"] = _page_number(params.get("limit"), DEFAULT_LIMIT, 1, max(PAGE_SIZES))
    body["offset"] = _page_number(params.get("offset"), 0, 0, None)
    return body


def _page_number(raw: str | None, default: int, low: int, high: int | None) -> int:
    try:
        value = int(raw or default)
    except ValueError:
        return default
    value = max(low, value)
    return value if high is None else min(high, value)


async def call(request: Request, method: str, path: str, **kwargs: Any) -> Any:
    """The decoded backend response, or a `BackendError` with a message fit to
    put on the page. The backend's error bodies are `{"detail": ...}`."""
    try:
        response = await request.app.state.backend.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        raise BackendError(UNREACHABLE) from exc
    if response.is_success:
        return response.json()
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    raise BackendError(str(detail) if detail else UNREACHABLE)


def render(request: Request, template: str, context: dict[str, Any]):
    return TEMPLATES.TemplateResponse(request, template, context)


router = APIRouter()


async def results_context(request: Request) -> dict[str, Any]:
    body = query_body(request.query_params)
    results = await call(request, "QUERY", PATH, json=body)
    return {
        "accommodations": results["accommodations"],
        "page_sizes": PAGE_SIZES,
        "total": results["total"],
        "limit": body["limit"],
        "offset": body["offset"],
        "params": request.query_params,
    }


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Reports this service and the backend behind it, the same way the backend
    reports the database service."""
    try:
        body = await call(request, "GET", "/health")
    except BackendError:
        backend_status = "unreachable"
    else:
        backend_status = str(body.get("status", "unknown"))
    return {
        "status": "ok" if backend_status == "ok" else "degraded",
        "service": request.app.state.settings.service_name,
        "backend": backend_status,
    }


@router.get("/")
async def index(request: Request):
    """The whole page. The results are rendered server-side on first load, so
    the list is there before HTMX has done anything."""
    context: dict[str, Any] = {
        "page_sizes": PAGE_SIZES,
        "limit": DEFAULT_LIMIT,
        # Also set by results_context, but the form still has to render with
        # the user's filters when the backend call fails.
        "params": request.query_params,
    }
    try:
        context |= await results_context(request)
    except BackendError as exc:
        context["error"] = str(exc)
    return render(request, "page.html", context)


@router.get(PATH)
async def results(request: Request):
    """The list, the pager and nothing else -- what every search, every filter
    change and every page link swaps into #results."""
    try:
        context = await results_context(request)
    except BackendError as exc:
        return render(request, "partials/error.html", {"error": str(exc)})
    return render(request, "partials/results.html", context)


@router.get(f"{PATH}/{{accommodation_id:uuid}}")
async def detail(request: Request, accommodation_id: UUID):
    """One accommodation in full, as the modal."""
    try:
        accommodation = await call(request, "GET", f"{PATH}/{accommodation_id}")
    except BackendError as exc:
        return render(request, "partials/error.html", {"error": str(exc)})
    return render(request, "partials/modal.html", {"accommodation": accommodation})


def create_app(settings: Settings | None = None, *, transport: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # `transport` is the same test seam the other two services use.
        backend = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=settings.backend_timeout,
            transport=transport,
        )
        app.state.settings = settings
        app.state.backend = backend
        yield
        await backend.aclose()

    app = FastAPI(title="Accommodation Frontend Service", lifespan=lifespan)
    app.mount(
        "/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static"
    )
    app.include_router(router)
    return app


app = create_app()
