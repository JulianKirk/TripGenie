from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .client import BackendApiClient
from .config import Settings
from .errors import ApiError
from .models import (
    AvailabilityStatus,
    DependencyStatus,
    FrontendHealthDependencies,
    HealthResponse,
    PlanStatus,
    TransportOptionRecord,
    TransportPlanEntryRecord,
    TransportType,
    TripDirectory,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))

MAX_COMPARE_SELECTION = 4

TYPE_OPTIONS = [
    (item.value, item.value.replace("_", " ").title()) for item in TransportType
]
AVAILABILITY_OPTIONS = [
    (item.value, item.value.replace("_", " ").title()) for item in AvailabilityStatus
]
PLAN_STATUS_OPTIONS = [
    (PlanStatus.PENDING.value, "Shortlisted"),
    (PlanStatus.CONFIRMED.value, "In the itinerary"),
    (PlanStatus.COMPLETED.value, "Journey taken"),
    (PlanStatus.CANCELLED.value, "Removed"),
]
# Real civil UTC offsets, including the half and quarter hour ones, so the
# field is a pick rather than a number of minutes the user has to work out.
_UTC_OFFSET_MINUTES = (
    -720, -660, -600, -570, -540, -480, -420, -360, -300, -240, -210, -180,
    -120, -60, 0, 60, 120, 180, 210, 240, 270, 300, 330, 345, 360, 390, 420,
    480, 525, 540, 570, 600, 630, 660, 690, 720, 765, 780, 840,
)


def _offset_label(minutes: int) -> str:
    sign = "-" if minutes < 0 else "+"
    hours, remainder = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{remainder:02d}"


UTC_OFFSET_OPTIONS = [
    ("", "Not specified"),
    *[(str(minutes), _offset_label(minutes)) for minutes in _UTC_OFFSET_MINUTES],
]

FILTER_TYPE_OPTIONS = [("", "All transport types"), *TYPE_OPTIONS]
FILTER_AVAILABILITY_OPTIONS = [("", "Any availability"), *AVAILABILITY_OPTIONS]

# Filters the browse screen forwards to the backend. Blank values are dropped so
# an empty form field is not sent as an empty query parameter, which the backend
# rejects as blank rather than treating as "unset".
FILTER_FIELDS = (
    "type",
    "provider",
    "origin",
    "destination",
    "availability_status",
    "min_price",
    "max_price",
    "departure_from",
    "departure_to",
)

OPTION_FIELDS = (
    "type",
    "provider",
    "origin",
    "destination",
    "departure_time",
    "arrival_time",
    "departure_utc_offset",
    "arrival_utc_offset",
    "price",
    "capacity",
    "availability_status",
    "notes",
)
INTEGER_OPTION_FIELDS = frozenset(
    {"capacity", "departure_utc_offset", "arrival_utc_offset"},
)
FLOAT_OPTION_FIELDS = frozenset({"price"})


def transport_choices(
    options: list[TransportOptionRecord],
) -> list[tuple[str, str]]:
    """Readable labels for the transport picker, ordered as the list is."""
    return [
        ("", "Select a transport option"),
        *[
            (
                option.id,
                f"{option.origin} to {option.destination} - {option.provider}"
                f" - {option.type_label} - {option.departure_time}"
                f" - ${option.price:.2f}",
            )
            for option in options
        ],
    ]


def trip_choices(directory: TripDirectory) -> list[tuple[str, str]]:
    return [
        ("", "Select a trip"),
        *[(trip.id, trip.label) for trip in directory.trips],
    ]


TRIPS_UNAVAILABLE_HINT = (
    "The Student 1 trips service is unavailable, so the trip list could not be "
    "loaded. Enter the trip identifier directly, for example "
    "trip_2026_sydney_long_weekend."
)


def get_backend_client(request: Request) -> BackendApiClient:
    return request.app.state.backend_client


ClientDep = Annotated[BackendApiClient, Depends(get_backend_client)]


def envelope(payload: object) -> dict[str, object]:
    return {"data": payload}


def path_for(request: Request, route_name: str, **path_params: str) -> str:
    return str(request.app.url_path_for(route_name, **path_params))


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def error_details_by_field(error: ApiError | None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    if error is None:
        return grouped

    for detail in error.details:
        field = detail.get("field", "general")
        grouped.setdefault(field, []).append(detail.get("issue", "Invalid value."))
    return grouped


def _clean_filters(raw: dict[str, str | None]) -> dict[str, str]:
    return {
        name: value.strip()
        for name, value in raw.items()
        if value is not None and value.strip()
    }


def _numeric_or_text(name: str, value: str) -> object:
    """Send numbers as numbers so the backend reports type errors, not blanks.

    A non-numeric entry is forwarded as-is: the backend owns validation, and its
    message is more precise than anything guessed here.
    """
    try:
        if name in INTEGER_OPTION_FIELDS:
            return int(value)
        if name in FLOAT_OPTION_FIELDS:
            return float(value)
    except ValueError:
        return value

    return value


def _option_payload(form: dict[str, str]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for name in OPTION_FIELDS:
        value = (form.get(name) or "").strip()
        if not value:
            continue
        payload[name] = _numeric_or_text(name, value)

    identifier = (form.get("id") or "").strip()
    if identifier:
        payload["id"] = identifier

    return payload


def _entry_payload(form: dict[str, str]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for name in ("trip_id", "transport_id", "booking_date", "booking_status", "notes"):
        value = (form.get(name) or "").strip()
        if value:
            payload[name] = value

    travellers = (form.get("traveller_count") or "").strip()
    if travellers:
        try:
            payload["traveller_count"] = int(travellers)
        except ValueError:
            payload["traveller_count"] = travellers

    cost = (form.get("estimated_cost") or "").strip()
    if cost:
        try:
            payload["estimated_cost"] = float(cost)
        except ValueError:
            payload["estimated_cost"] = cost

    identifier = (form.get("id") or "").strip()
    if identifier:
        payload["id"] = identifier

    return payload


def empty_option_form() -> dict[str, str]:
    return {
        "id": "",
        "type": TransportType.FLIGHT.value,
        "provider": "",
        "origin": "",
        "destination": "",
        "departure_time": "",
        "arrival_time": "",
        "departure_utc_offset": "",
        "arrival_utc_offset": "",
        "price": "",
        "capacity": "1",
        "availability_status": AvailabilityStatus.AVAILABLE.value,
        "notes": "",
    }


def option_to_form(option: TransportOptionRecord) -> dict[str, str]:
    return {
        "id": option.id,
        "type": option.type.value,
        "provider": option.provider,
        "origin": option.origin,
        "destination": option.destination,
        "departure_time": option.departure_time,
        "arrival_time": option.arrival_time,
        "departure_utc_offset": (
            "" if option.departure_utc_offset is None
            else str(option.departure_utc_offset)
        ),
        "arrival_utc_offset": (
            "" if option.arrival_utc_offset is None else str(option.arrival_utc_offset)
        ),
        "price": f"{option.price:.2f}",
        "capacity": str(option.capacity),
        "availability_status": option.availability_status.value,
        "notes": option.notes or "",
    }


def entry_to_form(entry: TransportPlanEntryRecord) -> dict[str, str]:
    return {
        "id": entry.id,
        "trip_id": entry.trip_id,
        "transport_id": entry.transport_id,
        "traveller_count": str(entry.traveller_count),
        "booking_date": entry.booking_date,
        "estimated_cost": f"{entry.estimated_cost:.2f}",
        "booking_status": entry.booking_status.value,
        "notes": entry.notes or "",
    }


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = BackendApiClient(app_settings, transport=transport)
        app.state.backend_client = client
        try:
            yield
        finally:
            await client.close()

    app = FastAPI(
        title="TripGenie Student 3 Transport Frontend",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_ROOT / "static")),
        name="static",
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
        )

    def render(
        request: Request,
        content_template: str,
        *,
        page_title: str,
        status_code: int = 200,
        **context: object,
    ) -> Response:
        """Render a screen, as a fragment for HTMX and a full page otherwise.

        The shell sets hx-target="#app-shell" with hx-swap="outerHTML", so a
        boosted request that answered with the whole document would nest a
        second <head> and site header inside the shell, and they would stack up
        with every navigation. Answering with the shell alone keeps the swap to
        the region HTMX is replacing, while a normal request still gets a
        complete, independently viewable page.
        """
        template = (
            "partials/app_shell.html" if is_htmx_request(request) else "page.html"
        )
        return TEMPLATES.TemplateResponse(
            request,
            template,
            {
                "page_title": page_title,
                "content_template": content_template,
                "service_name": app_settings.service_name,
                **context,
            },
            status_code=status_code,
        )

    def render_error(
        request: Request,
        error: ApiError,
        *,
        title: str,
        retry_url: str,
        options: list[TransportOptionRecord] | None = None,
        option_list_error: ApiError | None = None,
    ) -> Response:
        return render(
            request,
            "partials/error_state.html",
            page_title=title,
            status_code=200,
            error=error,
            error_title=title,
            retry_url=retry_url,
            options=options or [],
            option_list_error=option_list_error,
            selected_option_id=None,
            filters={},
        )

    async def safe_list_options(
        client: BackendApiClient,
        params: dict[str, str] | None = None,
    ) -> tuple[list[TransportOptionRecord], ApiError | None]:
        try:
            return await client.list_transport_options(params), None
        except ApiError as exc:
            return [], exc

    # ------------------------------------------------------------- operations

    @app.get("/health", response_model=None)
    async def health(client: ClientDep) -> Response:
        try:
            payload = await client.health()
            backend = DependencyStatus(
                status="ok" if payload.status == "ok" else "degraded",
                service=payload.service,
                detail="Backend API responded successfully.",
            )
        except ApiError as exc:
            backend = DependencyStatus(
                status="unavailable",
                service="student-3-backend",
                detail=exc.message,
                code=exc.code,
            )

        body = HealthResponse(
            status="ok" if backend.status == "ok" else "degraded",
            service=app_settings.service_name,
            dependencies=FrontendHealthDependencies(backend=backend),
        )
        return JSONResponse(envelope(body.model_dump(mode="json")))

    @app.get("/ready", response_model=None)
    async def ready(client: ClientDep) -> Response:
        try:
            payload = await client.ready()
            is_ready = payload.status == "ok"
            backend = DependencyStatus(
                status="ok" if is_ready else "degraded",
                service=payload.service,
                detail="Backend API reported readiness.",
            )
        except ApiError as exc:
            is_ready = False
            backend = DependencyStatus(
                status="unavailable",
                service="student-3-backend",
                detail=exc.message,
                code=exc.code,
            )

        body = HealthResponse(
            status="ok" if is_ready else "unavailable",
            service=app_settings.service_name,
            dependencies=FrontendHealthDependencies(backend=backend),
        )
        return JSONResponse(
            envelope(body.model_dump(mode="json")),
            status_code=200 if is_ready else 503,
        )

    # ------------------------------------------------------------------ browse

    @app.get("/", name="browse", response_model=None)
    async def browse(
        request: Request,
        client: ClientDep,
        transport_type: Annotated[str | None, Query(alias="type")] = None,
        provider: Annotated[str | None, Query()] = None,
        origin: Annotated[str | None, Query()] = None,
        destination: Annotated[str | None, Query()] = None,
        availability_status: Annotated[str | None, Query()] = None,
        min_price: Annotated[str | None, Query()] = None,
        max_price: Annotated[str | None, Query()] = None,
        departure_from: Annotated[str | None, Query()] = None,
        departure_to: Annotated[str | None, Query()] = None,
    ) -> Response:
        filters = _clean_filters(
            {
                "type": transport_type,
                "provider": provider,
                "origin": origin,
                "destination": destination,
                "availability_status": availability_status,
                "min_price": min_price,
                "max_price": max_price,
                "departure_from": departure_from,
                "departure_to": departure_to,
            },
        )
        options, list_error = await safe_list_options(client, filters)
        if list_error is not None:
            return render_error(
                request,
                list_error,
                title="Transport options are unavailable",
                retry_url=path_for(request, "browse"),
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/option_list.html",
            page_title="Browse transport",
            options=options,
            option_list_error=None,
            selected_option_id=None,
            filters=filters,
            type_options=FILTER_TYPE_OPTIONS,
            availability_options=FILTER_AVAILABILITY_OPTIONS,
            is_filtered=bool(filters),
        )

    @app.get("/compare", name="compare", response_model=None)
    async def compare(
        request: Request,
        client: ClientDep,
        ids: Annotated[list[str] | None, Query()] = None,
    ) -> Response:
        selected = [value.strip() for value in (ids or []) if value.strip()]
        options, list_error = await safe_list_options(client)

        compared: list[TransportOptionRecord] = []
        compare_error: ApiError | None = None
        if selected:
            try:
                compared = await client.compare_transport_options(selected)
            except ApiError as exc:
                compare_error = exc

        return render(
            request,
            "partials/option_compare.html",
            page_title="Compare transport",
            options=options,
            option_list_error=list_error,
            selected_option_id=None,
            filters={},
            selected_ids=selected,
            compared=compared,
            compare_error=compare_error,
            compare_limit=MAX_COMPARE_SELECTION,
        )

    # -------------------------------------------------------- AI suggestions

    def ai_context(
        options: list[TransportOptionRecord],
        directory: TripDirectory,
    ) -> dict[str, object]:
        return {
            "trip_options": trip_choices(directory),
            "trips_available": directory.available,
            "trips_unavailable_hint": TRIPS_UNAVAILABLE_HINT,
        }

    def empty_ai_form() -> dict[str, str]:
        return {"trip_id": "", "origin": "", "destination": "", "question": ""}

    @app.get("/suggestions", name="ai_form", response_model=None)
    async def ai_form(
        request: Request,
        client: ClientDep,
        trip_id: Annotated[str | None, Query()] = None,
        origin: Annotated[str | None, Query()] = None,
        destination: Annotated[str | None, Query()] = None,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        directory = await client.trip_directory()
        form = empty_ai_form() | {
            "trip_id": (trip_id or "").strip(),
            "origin": (origin or "").strip(),
            "destination": (destination or "").strip(),
        }
        return render(
            request,
            "partials/ai_recommendations.html",
            page_title="Transport suggestions",
            options=options,
            option_list_error=list_error,
            selected_option_id=None,
            filters={},
            form=form,
            form_action=path_for(request, "ai_suggest"),
            errors_by_field={},
            error=None,
            recommendation=None,
            **ai_context(options, directory),
        )

    @app.post("/suggestions", name="ai_suggest", response_model=None)
    async def ai_suggest(request: Request, client: ClientDep) -> Response:
        form = dict(await request.form())
        submitted = {key: str(value) for key, value in form.items()}
        payload: dict[str, object] = {}
        for name in ("trip_id", "origin", "destination", "question"):
            value = (submitted.get(name) or "").strip()
            if value:
                payload[name] = value

        options, list_error = await safe_list_options(client)
        directory = await client.trip_directory()
        recommendation = None
        error: ApiError | None = None
        try:
            recommendation = await client.recommend_transport(payload)
        except ApiError as exc:
            error = exc

        return render(
            request,
            "partials/ai_recommendations.html",
            page_title="Transport suggestions",
            options=options,
            option_list_error=list_error,
            selected_option_id=None,
            filters={},
            form=empty_ai_form() | submitted,
            form_action=path_for(request, "ai_suggest"),
            errors_by_field=error_details_by_field(error),
            error=error,
            recommendation=recommendation,
            **ai_context(options, directory),
        )

    # ------------------------------------------------------------ option CRUD

    @app.get("/options/new", name="new_option_form", response_model=None)
    async def new_option_form(request: Request, client: ClientDep) -> Response:
        options, list_error = await safe_list_options(client)
        return render(
            request,
            "partials/option_form.html",
            page_title="Add transport option",
            options=options,
            option_list_error=list_error,
            selected_option_id=None,
            filters={},
            form=empty_option_form(),
            form_action=path_for(request, "create_option"),
            form_title="Add transport option",
            submit_label="Add option",
            errors_by_field={},
            error=None,
            type_options=TYPE_OPTIONS,
            availability_options=AVAILABILITY_OPTIONS,
            utc_offset_options=UTC_OFFSET_OPTIONS,
        )

    @app.post("/options", name="create_option", response_model=None)
    async def create_option(request: Request, client: ClientDep) -> Response:
        form = dict(await request.form())
        submitted = {key: str(value) for key, value in form.items()}
        try:
            created = await client.create_transport_option(_option_payload(submitted))
        except ApiError as exc:
            options, list_error = await safe_list_options(client)
            return render(
                request,
                "partials/option_form.html",
                page_title="Add transport option",
                status_code=200,
                options=options,
                option_list_error=list_error,
                selected_option_id=None,
                filters={},
                form={**empty_option_form(), **submitted},
                form_action=path_for(request, "create_option"),
                form_title="Add transport option",
                submit_label="Add option",
                errors_by_field=error_details_by_field(exc),
                error=exc,
                type_options=TYPE_OPTIONS,
                availability_options=AVAILABILITY_OPTIONS,
                utc_offset_options=UTC_OFFSET_OPTIONS,
            )

        return RedirectResponse(
            path_for(request, "view_option", transport_id=created.id),
            status_code=303,
        )

    @app.get("/options/{transport_id}", name="view_option", response_model=None)
    async def view_option(
        request: Request,
        transport_id: str,
        client: ClientDep,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        try:
            option = await client.get_transport_option(transport_id)
            entries = await client.list_entries_for_option(transport_id)
        except ApiError as exc:
            return render_error(
                request,
                exc,
                title="Transport option unavailable",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/option_detail.html",
            page_title=f"{option.origin} to {option.destination}",
            options=options,
            option_list_error=list_error,
            selected_option_id=option.id,
            filters={},
            option=option,
            entries=entries,
        )

    @app.get(
        "/options/{transport_id}/edit",
        name="edit_option_form",
        response_model=None,
    )
    async def edit_option_form(
        request: Request,
        transport_id: str,
        client: ClientDep,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        try:
            option = await client.get_transport_option(transport_id)
        except ApiError as exc:
            return render_error(
                request,
                exc,
                title="Transport option unavailable",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/option_form.html",
            page_title="Edit transport option",
            options=options,
            option_list_error=list_error,
            selected_option_id=option.id,
            filters={},
            form=option_to_form(option),
            form_action=path_for(request, "update_option", transport_id=option.id),
            form_title="Edit transport option",
            submit_label="Save changes",
            errors_by_field={},
            error=None,
            type_options=TYPE_OPTIONS,
            availability_options=AVAILABILITY_OPTIONS,
            utc_offset_options=UTC_OFFSET_OPTIONS,
            is_edit=True,
        )

    @app.post(
        "/options/{transport_id}/edit",
        name="update_option",
        response_model=None,
    )
    async def update_option(
        request: Request,
        transport_id: str,
        client: ClientDep,
    ) -> Response:
        form = dict(await request.form())
        submitted = {key: str(value) for key, value in form.items()}
        payload = _option_payload(submitted)
        payload.pop("id", None)
        try:
            await client.update_transport_option(transport_id, payload)
        except ApiError as exc:
            options, list_error = await safe_list_options(client)
            return render(
                request,
                "partials/option_form.html",
                page_title="Edit transport option",
                status_code=200,
                options=options,
                option_list_error=list_error,
                selected_option_id=transport_id,
                filters={},
                form={**empty_option_form(), **submitted, "id": transport_id},
                form_action=path_for(
                    request,
                    "update_option",
                    transport_id=transport_id,
                ),
                form_title="Edit transport option",
                submit_label="Save changes",
                errors_by_field=error_details_by_field(exc),
                error=exc,
                type_options=TYPE_OPTIONS,
                availability_options=AVAILABILITY_OPTIONS,
                utc_offset_options=UTC_OFFSET_OPTIONS,
                is_edit=True,
            )

        return RedirectResponse(
            path_for(request, "view_option", transport_id=transport_id),
            status_code=303,
        )

    @app.get(
        "/options/{transport_id}/delete",
        name="delete_option_confirmation",
        response_model=None,
    )
    async def delete_option_confirmation(
        request: Request,
        transport_id: str,
        client: ClientDep,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        try:
            option = await client.get_transport_option(transport_id)
            entries = await client.list_entries_for_option(transport_id)
        except ApiError as exc:
            return render_error(
                request,
                exc,
                title="Transport option unavailable",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/delete_confirmation.html",
            page_title="Remove transport option",
            options=options,
            option_list_error=list_error,
            selected_option_id=option.id,
            filters={},
            confirm_title="Remove this transport option?",
            confirm_body=(
                f"{option.type_label} with {option.provider}, "
                f"{option.origin} to {option.destination}."
            ),
            blocked_reason=(
                f"{len(entries)} trip(s) still plan this transport. Remove those "
                "entries first."
                if entries
                else None
            ),
            form_action=path_for(request, "delete_option", transport_id=option.id),
            cancel_url=path_for(request, "view_option", transport_id=option.id),
            error=None,
        )

    @app.post(
        "/options/{transport_id}/delete",
        name="delete_option",
        response_model=None,
    )
    async def delete_option(
        request: Request,
        transport_id: str,
        client: ClientDep,
    ) -> Response:
        try:
            await client.delete_transport_option(transport_id)
        except ApiError as exc:
            options, list_error = await safe_list_options(client)
            return render(
                request,
                "partials/delete_confirmation.html",
                page_title="Remove transport option",
                options=options,
                option_list_error=list_error,
                selected_option_id=transport_id,
                filters={},
                confirm_title="Remove this transport option?",
                confirm_body="",
                blocked_reason=None,
                form_action=path_for(
                    request,
                    "delete_option",
                    transport_id=transport_id,
                ),
                cancel_url=path_for(
                    request,
                    "view_option",
                    transport_id=transport_id,
                ),
                error=exc,
            )

        return RedirectResponse(path_for(request, "browse"), status_code=303)

    # -------------------------------------------------------- trip transport

    @app.get("/trips/{trip_id}/transport", name="trip_transport", response_model=None)
    async def trip_transport(
        request: Request,
        trip_id: str,
        client: ClientDep,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        try:
            summary = await client.trip_transport(trip_id)
        except ApiError as exc:
            return render_error(
                request,
                exc,
                title="Trip transport unavailable",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/trip_transport.html",
            page_title="Trip transport",
            options=options,
            option_list_error=list_error,
            selected_option_id=None,
            filters={},
            summary=summary,
            trip_id=trip_id,
        )

    # ---------------------------------------------------------- plan entries

    def entry_form_context(
        options: list[TransportOptionRecord],
        directory: TripDirectory,
    ) -> dict[str, object]:
        """Shared picker context for every plan-entry form render."""
        return {
            "plan_status_options": PLAN_STATUS_OPTIONS,
            "trip_options": trip_choices(directory),
            "trips_available": directory.available,
            "trips_unavailable_hint": TRIPS_UNAVAILABLE_HINT,
            "transport_options_choices": transport_choices(options),
        }

    @app.get("/plan/new", name="new_entry_form", response_model=None)
    async def new_entry_form(
        request: Request,
        client: ClientDep,
        transport_id: Annotated[str | None, Query()] = None,
        trip_id: Annotated[str | None, Query()] = None,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        directory = await client.trip_directory()
        form = {
            "id": "",
            "trip_id": (trip_id or "").strip(),
            "transport_id": (transport_id or "").strip(),
            "traveller_count": "1",
            "booking_date": "",
            "estimated_cost": "",
            "booking_status": PlanStatus.PENDING.value,
            "notes": "",
        }
        return render(
            request,
            "partials/plan_entry_form.html",
            page_title="Add transport to a trip",
            options=options,
            option_list_error=list_error,
            selected_option_id=form["transport_id"] or None,
            filters={},
            form=form,
            form_action=path_for(request, "create_entry"),
            form_title="Add transport to a trip",
            submit_label="Add to trip",
            errors_by_field={},
            error=None,
            **entry_form_context(options, directory),
        )

    @app.post("/plan", name="create_entry", response_model=None)
    async def create_entry(request: Request, client: ClientDep) -> Response:
        form = dict(await request.form())
        submitted = {key: str(value) for key, value in form.items()}
        try:
            created = await client.create_plan_entry(_entry_payload(submitted))
        except ApiError as exc:
            options, list_error = await safe_list_options(client)
            directory = await client.trip_directory()
            return render(
                request,
                "partials/plan_entry_form.html",
                page_title="Add transport to a trip",
                options=options,
                option_list_error=list_error,
                selected_option_id=submitted.get("transport_id") or None,
                filters={},
                form=submitted,
                form_action=path_for(request, "create_entry"),
                form_title="Add transport to a trip",
                submit_label="Add to trip",
                errors_by_field=error_details_by_field(exc),
                error=exc,
                **entry_form_context(options, directory),
            )

        return RedirectResponse(
            path_for(request, "trip_transport", trip_id=created.trip_id),
            status_code=303,
        )

    @app.get("/plan/{booking_id}/edit", name="edit_entry_form", response_model=None)
    async def edit_entry_form(
        request: Request,
        booking_id: str,
        client: ClientDep,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        directory = await client.trip_directory()
        try:
            entry = await client.get_plan_entry(booking_id)
        except ApiError as exc:
            return render_error(
                request,
                exc,
                title="Plan entry unavailable",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/plan_entry_form.html",
            page_title="Edit planned transport",
            options=options,
            option_list_error=list_error,
            selected_option_id=entry.transport_id,
            filters={},
            form=entry_to_form(entry),
            form_action=path_for(request, "update_entry", booking_id=entry.id),
            form_title="Edit planned transport",
            submit_label="Save changes",
            errors_by_field={},
            error=None,
            is_edit=True,
            cancel_url=path_for(request, "trip_transport", trip_id=entry.trip_id),
            **entry_form_context(options, directory),
        )

    @app.post("/plan/{booking_id}/edit", name="update_entry", response_model=None)
    async def update_entry(
        request: Request,
        booking_id: str,
        client: ClientDep,
    ) -> Response:
        form = dict(await request.form())
        submitted = {key: str(value) for key, value in form.items()}
        payload = _entry_payload(submitted)
        payload.pop("id", None)
        try:
            updated = await client.update_plan_entry(booking_id, payload)
        except ApiError as exc:
            options, list_error = await safe_list_options(client)
            directory = await client.trip_directory()
            return render(
                request,
                "partials/plan_entry_form.html",
                page_title="Edit planned transport",
                options=options,
                option_list_error=list_error,
                selected_option_id=submitted.get("transport_id") or None,
                filters={},
                form={**submitted, "id": booking_id},
                form_action=path_for(request, "update_entry", booking_id=booking_id),
                form_title="Edit planned transport",
                submit_label="Save changes",
                errors_by_field=error_details_by_field(exc),
                error=exc,
                is_edit=True,
                **entry_form_context(options, directory),
            )

        return RedirectResponse(
            path_for(request, "trip_transport", trip_id=updated.trip_id),
            status_code=303,
        )

    @app.get(
        "/plan/{booking_id}/delete",
        name="delete_entry_confirmation",
        response_model=None,
    )
    async def delete_entry_confirmation(
        request: Request,
        booking_id: str,
        client: ClientDep,
    ) -> Response:
        options, list_error = await safe_list_options(client)
        try:
            entry = await client.get_plan_entry(booking_id)
        except ApiError as exc:
            return render_error(
                request,
                exc,
                title="Plan entry unavailable",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return render(
            request,
            "partials/delete_confirmation.html",
            page_title="Remove planned transport",
            options=options,
            option_list_error=list_error,
            selected_option_id=entry.transport_id,
            filters={},
            confirm_title="Remove this transport from the trip?",
            confirm_body=(
                f"{entry.traveller_count} traveller(s), planned "
                f"{entry.booking_date}, estimated ${entry.estimated_cost:.2f}."
            ),
            blocked_reason=None,
            form_action=path_for(request, "delete_entry", booking_id=entry.id),
            cancel_url=path_for(request, "trip_transport", trip_id=entry.trip_id),
            error=None,
        )

    @app.post("/plan/{booking_id}/delete", name="delete_entry", response_model=None)
    async def delete_entry(
        request: Request,
        booking_id: str,
        client: ClientDep,
    ) -> Response:
        try:
            entry = await client.get_plan_entry(booking_id)
            await client.delete_plan_entry(booking_id)
        except ApiError as exc:
            options, list_error = await safe_list_options(client)
            return render_error(
                request,
                exc,
                title="Unable to remove planned transport",
                retry_url=path_for(request, "browse"),
                options=options,
                option_list_error=list_error,
            )

        return RedirectResponse(
            path_for(request, "trip_transport", trip_id=entry.trip_id),
            status_code=303,
        )


    return app


app = create_app()


def filter_query(filters: dict[str, str]) -> str:
    """Re-encode active filters so links preserve the current browse state."""
    return urlencode(filters) if filters else ""


TEMPLATES.env.globals["filter_query"] = filter_query
TEMPLATES.env.globals["FILTER_FIELDS"] = FILTER_FIELDS
