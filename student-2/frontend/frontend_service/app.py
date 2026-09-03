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
from urllib.parse import parse_qs
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import QueryParams

from frontend_service.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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


def form_values(body: dict[str, Any]) -> QueryParams:
    """A QUERY body, back as the filter form that would have produced it.

    The inverse of `query_body`, over the same four field maps, so there is one
    place where a filter's form name and its message name are paired up. It
    exists for the ask box: the answer arrives as a search, and the form has to
    show it.

    A QueryParams rather than a dict because that is what the template already
    reads -- `.get` for an input, `.getlist` for the amenity boxes -- so the AI
    path renders the identical partial with no template branching.
    """
    match = body.get("accommodation", {})
    pairs: list[tuple[str, str]] = []
    for source, fields in (
        (match, MATCH_FIELDS),
        (match.get("location_details", {}), LOCATION_FIELDS),
        (match.get("room_details", {}), ROOM_FIELDS),
    ):
        pairs += [
            (form_field, str(source[message_field]))
            for form_field, message_field in fields.items()
            if source.get(message_field) is not None
        ]
    pairs += [(field, str(body[field])) for field in BOUND_FIELDS if field in body]
    pairs += [("amenities", amenity) for amenity in match.get("amenities") or []]
    if "limit" in body:
        pairs.append(("limit", str(body["limit"])))
    return QueryParams(pairs)


def understood(params: QueryParams) -> list[str]:
    """The filters, as the short phrases the notice above the results reads out.

    ponytail: `field: value`, not a sentence per filter. The reader is checking
    the question was not misread, and the filter form right below says the same
    thing in full.
    """
    return [
        f"{key.replace('_', ' ')} {value}"
        for key, value in params.multi_items()
        if key != "limit"
    ]


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
    return render(request, "partials/search_results.html", context)


@router.post(f"{PATH}/ai-search")
async def ai_search(request: Request):
    """A question in English. The backend turns it into filters and runs the
    ordinary search; this renders the rows, says how the question was read, and
    sends the filter form back out of band carrying the same filters.

    A blank ask is the unfiltered list, not an error -- the same answer an empty
    search box gives.
    """
    # ponytail: `parse_qs` rather than `request.form()` or a FastAPI
    # `Form(...)` parameter. Both of those need python-multipart -- a whole
    # dependency for the one urlencoded field this page will never send as
    # multipart. Switch to `Form(...)` if a file upload ever lands here.
    fields = parse_qs((await request.body()).decode())
    question = (fields.get("query") or [""])[0].strip()
    if not question:
        return await results(request)
    try:
        found = await call(
            request,
            "POST",
            f"{PATH}/ai-search",
            json={"query": question},
            # Not the page's ordinary 5s: there is a model at the other end.
            timeout=request.app.state.settings.ai_timeout,
        )
    except BackendError as exc:
        return render(request, "partials/error.html", {"error": str(exc)})

    params = form_values(found["query_used"])
    return render(
        request,
        "partials/ai_results.html",
        {
            "accommodations": found["accommodations"],
            "page_sizes": PAGE_SIZES,
            "total": found["total"],
            "limit": found["query_used"]["limit"],
            "offset": found["query_used"]["offset"],
            "params": params,
            "understood": understood(params),
            "reply": found["reply"],
        },
    )


@router.get(f"{PATH}/{{accommodation_id:uuid}}")
async def detail(request: Request, accommodation_id: UUID):
    """One accommodation in full, as the modal."""
    try:
        accommodation = await call(request, "GET", f"{PATH}/{accommodation_id}")
    except BackendError as exc:
        return render(request, "partials/error.html", {"error": str(exc)})
    return render(request, "partials/modal.html", {"accommodation": accommodation})


@router.get(f"{PATH}/{{accommodation_id:uuid}}/itineraries")
async def itineraries(request: Request, accommodation_id: UUID):
    """The Add-to-Itinerary list, fetched when the user opens the disclosure."""
    return await _picker(request, accommodation_id, "GET", "")


@router.put(f"{PATH}/{{accommodation_id:uuid}}/itineraries/{{itinerary_id}}")
@router.delete(f"{PATH}/{{accommodation_id:uuid}}/itineraries/{{itinerary_id}}")
async def toggle_itinerary(request: Request, accommodation_id: UUID, itinerary_id: str):
    """One handler for both verbs: the ticked box sends DELETE and the unticked
    one sends PUT, and the backend answers both with the whole list."""
    return await _picker(
        request, accommodation_id, request.method, f"/{itinerary_id}", itinerary_id
    )


async def _picker(
    request: Request,
    accommodation_id: UUID,
    method: str,
    suffix: str,
    itinerary_id: str = "",
):
    path = f"{PATH}/{accommodation_id}/itineraries{suffix}"
    try:
        body = await call(request, method, path)
    except BackendError as exc:
        return render(request, "partials/error.html", {"error": str(exc)})
    return render(
        request,
        "partials/itinerary_picker.html",
        {
            "itineraries": body["itineraries"],
            "accommodation_id": accommodation_id,
            "toast": _added_message(method, itinerary_id, body["itineraries"]),
        },
    )


def _added_message(
    method: str, itinerary_id: str, itineraries: list[dict[str, Any]]
) -> str:
    """What the toast says, or "" for no toast.

    Only an add announces itself. A removal already had the user confirm it, so
    telling them it happened is a second interruption for the same decision.
    The name comes from the repainted list rather than the request, so the toast
    cannot name something the backend did not actually store.
    """
    if method != "PUT":
        return ""
    for itinerary in itineraries:
        if itinerary["itinerary_id"] == itinerary_id and itinerary["selected"]:
            return f"Added to {itinerary['name']}."
    return ""


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
