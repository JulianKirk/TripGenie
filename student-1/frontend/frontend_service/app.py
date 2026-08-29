from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .client import BackendApiClient
from .config import Settings
from .errors import ApiError, validation_error
from .models import (
    DataEnvelope,
    DependencyStatus,
    FrontendHealthDependencies,
    HealthResponse,
    ItineraryCategory,
    ItineraryItemRecord,
    TripDay,
    TripDetail,
    TripRecord,
    TripStatus,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
TRIP_STATUS_OPTIONS = [
    (status.value, status.value.replace("_", " ").title()) for status in TripStatus
]
ITINERARY_CATEGORY_OPTIONS = [
    (category.value, category.value.replace("_", " ").title())
    for category in ItineraryCategory
]
FILTER_CATEGORY_OPTIONS = [("", "All categories"), *ITINERARY_CATEGORY_OPTIONS]
CATEGORY_VALUE_LIST = ", ".join(category.value for category in ItineraryCategory)
CREATE_TRIP_DESCRIPTION = (
    "Add a trip and keep browser CRUD separate from the backend API contract."
)
EDIT_TRIP_DESCRIPTION = (
    "Update trip details without bypassing the Student 1 backend service."
)
CREATE_ITEM_DESCRIPTION = (
    "Add a day-by-day itinerary entry through the public backend API."
)
EDIT_ITEM_DESCRIPTION = (
    "Adjust timing, location, and notes while keeping the backend contract "
    "authoritative."
)
RECOVER_TRIP_AFTER_ITEM_ERROR = (
    "Unable to recover the trip after itinerary validation failed"
)


def get_backend_client(request: Request) -> BackendApiClient:
    return request.app.state.backend_client


def envelope(payload: object) -> dict[str, object]:
    return {"data": payload}


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def path_for(request: Request, route_name: str, **path_params: str) -> str:
    return str(request.app.url_path_for(route_name, **path_params))


def error_details_by_field(error: ApiError | None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    if error is None:
        return grouped

    for detail in error.details:
        field = detail.get("field", "general")
        grouped.setdefault(field, []).append(detail.get("issue", "Invalid value."))
    return grouped


def safe_list_trips(
    client: BackendApiClient,
) -> tuple[list[TripRecord], ApiError | None]:
    try:
        return client.list_trips(), None
    except ApiError as exc:
        return [], exc


def empty_trip_form() -> dict[str, str]:
    return {
        "id": "",
        "name": "",
        "destination": "",
        "start_date": "",
        "end_date": "",
        "traveller_count": "1",
        "status": TripStatus.DRAFT.value,
        "notes": "",
    }


def trip_form_from_record(trip: TripRecord | TripDetail) -> dict[str, str]:
    return {
        "id": trip.id,
        "name": trip.name,
        "destination": trip.destination,
        "start_date": trip.start_date,
        "end_date": trip.end_date,
        "traveller_count": str(trip.traveller_count),
        "status": trip.status.value,
        "notes": trip.notes or "",
    }


def empty_item_form(date_value: str = "") -> dict[str, str]:
    return {
        "id": "",
        "date": date_value,
        "start_time": "",
        "end_time": "",
        "title": "",
        "location": "",
        "description": "",
        "category": ItineraryCategory.ACTIVITY.value,
        "notes": "",
    }


def item_form_from_record(item: ItineraryItemRecord) -> dict[str, str]:
    return {
        "id": item.id,
        "date": item.date,
        "start_time": item.start_time or "",
        "end_time": item.end_time or "",
        "title": item.title,
        "location": item.location or "",
        "description": item.description or "",
        "category": item.category.value,
        "notes": item.notes or "",
    }


def normalise_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


async def read_form_values(
    request: Request, field_names: tuple[str, ...]
) -> dict[str, str]:
    form = await request.form()
    values: dict[str, str] = {}
    for field_name in field_names:
        raw_value = form.get(field_name, "")
        values[field_name] = "" if raw_value is None else str(raw_value)
    return values


def trip_payload_from_form(
    values: dict[str, str], *, include_id: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": values["name"].strip(),
        "destination": values["destination"].strip(),
        "start_date": values["start_date"].strip(),
        "end_date": values["end_date"].strip(),
        "traveller_count": values["traveller_count"].strip(),
        "status": values["status"].strip(),
        "notes": values["notes"],
    }
    trip_id = values["id"].strip()
    if include_id and trip_id:
        payload["id"] = trip_id

    return payload


def item_payload_from_form(
    values: dict[str, str], *, include_id: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "date": values["date"].strip(),
        "start_time": normalise_optional_text(values["start_time"]),
        "end_time": normalise_optional_text(values["end_time"]),
        "title": values["title"].strip(),
        "location": normalise_optional_text(values["location"]),
        "description": normalise_optional_text(values["description"]),
        "category": values["category"].strip(),
        "notes": normalise_optional_text(values["notes"]),
    }
    item_id = values["id"].strip()
    if include_id and item_id:
        payload["id"] = item_id

    return payload


def iso_date_or_none(value: str | None) -> str | None:
    cleaned = normalise_optional_text(value)
    if cleaned is None:
        return None

    try:
        date.fromisoformat(cleaned)
    except ValueError:
        return None

    return cleaned


def validate_filter_state(
    trip: TripDetail,
    *,
    selected_date: str | None,
    category_value: str | None,
) -> tuple[list[TripDay], ApiError | None]:
    display_days = trip.days
    if selected_date:
        try:
            date.fromisoformat(selected_date)
        except ValueError:
            return trip.days, validation_error(
                "Select a valid trip date.",
                [
                    {
                        "field": "date",
                        "issue": "must be a valid ISO date in YYYY-MM-DD format",
                    },
                ],
            )

        if selected_date < trip.start_date or selected_date > trip.end_date:
            return trip.days, validation_error(
                "Select a date within the trip window.",
                [
                    {
                        "field": "date",
                        "issue": (
                            f"must fall between {trip.start_date} and "
                            f"{trip.end_date}"
                        ),
                    },
                ],
            )

        matching_days = [day for day in trip.days if day.date == selected_date]
        display_days = matching_days or [TripDay(date=selected_date, items=[])]

    if category_value:
        try:
            category = ItineraryCategory(category_value)
        except ValueError:
            return display_days, validation_error(
                "Select a supported itinerary category.",
                [
                    {
                        "field": "category",
                        "issue": f"must be one of: {CATEGORY_VALUE_LIST}",
                    },
                ],
            )

        filtered_days: list[TripDay] = []
        for day in display_days:
            filtered_items = [item for item in day.items if item.category == category]
            if selected_date is not None:
                filtered_days.append(TripDay(date=day.date, items=filtered_items))
            elif filtered_items:
                filtered_days.append(TripDay(date=day.date, items=filtered_items))

        display_days = filtered_days

    return display_days, None


def render_screen(
    request: Request,
    *,
    page_title: str,
    trips: list[TripRecord],
    selected_trip_id: str | None,
    content_template: str,
    trip_list_error: ApiError | None = None,
    status_code: int = 200,
    push_url: str | None = None,
    **context: object,
) -> Response:
    template_name = (
        "partials/app_shell.html" if is_htmx_request(request) else "page.html"
    )
    response = TEMPLATES.TemplateResponse(
        request,
        template_name,
        {
            "page_title": page_title,
            "trips": trips,
            "trip_list_error": trip_list_error,
            "selected_trip_id": selected_trip_id,
            "content_template": content_template,
            "trip_status_options": TRIP_STATUS_OPTIONS,
            "itinerary_category_options": ITINERARY_CATEGORY_OPTIONS,
            "filter_category_options": FILTER_CATEGORY_OPTIONS,
            **context,
        },
        status_code=status_code,
    )
    if push_url is not None and is_htmx_request(request):
        response.headers["HX-Push-Url"] = push_url
    return response


def render_home_screen(
    request: Request,
    *,
    trips: list[TripRecord],
    trip_list_error: ApiError | None = None,
    status_code: int = 200,
    push_url: str | None = None,
) -> Response:
    return render_screen(
        request,
        page_title="TripGenie Student 1",
        trips=trips,
        selected_trip_id=None,
        content_template="partials/home_empty.html",
        trip_list_error=trip_list_error,
        status_code=status_code,
        push_url=push_url,
        page_error=None,
    )


def render_error_screen(
    request: Request,
    *,
    error: ApiError,
    error_title: str,
    page_title: str,
    trips: list[TripRecord],
    selected_trip_id: str | None = None,
    trip_list_error: ApiError | None = None,
    retry_url: str | None = None,
    fallback_url: str | None = None,
) -> Response:
    return render_screen(
        request,
        page_title=page_title,
        trips=trips,
        selected_trip_id=selected_trip_id,
        content_template="partials/error_state.html",
        trip_list_error=trip_list_error,
        status_code=error.status_code,
        page_error=error,
        error_title=error_title,
        retry_url=retry_url,
        fallback_url=fallback_url,
    )


def render_trip_form_screen(
    request: Request,
    *,
    trips: list[TripRecord],
    selected_trip_id: str | None,
    trip_list_error: ApiError | None,
    form_title: str,
    form_description: str,
    form_action: str,
    submit_label: str,
    cancel_url: str,
    trip_form: dict[str, str],
    form_error: ApiError | None = None,
    show_id_field: bool = False,
    status_code: int = 200,
) -> Response:
    return render_screen(
        request,
        page_title=form_title,
        trips=trips,
        selected_trip_id=selected_trip_id,
        content_template="partials/trip_form.html",
        trip_list_error=trip_list_error,
        status_code=status_code,
        page_error=form_error,
        form_errors_by_field=error_details_by_field(form_error),
        form_title=form_title,
        form_description=form_description,
        form_action=form_action,
        submit_label=submit_label,
        cancel_url=cancel_url,
        trip_form=trip_form,
        show_id_field=show_id_field,
    )


def render_item_form_screen(
    request: Request,
    *,
    trip: TripDetail,
    trips: list[TripRecord],
    selected_trip_id: str,
    trip_list_error: ApiError | None,
    form_title: str,
    form_description: str,
    form_action: str,
    submit_label: str,
    cancel_url: str,
    item_form: dict[str, str],
    form_error: ApiError | None = None,
    show_id_field: bool = False,
    status_code: int = 200,
) -> Response:
    return render_screen(
        request,
        page_title=form_title,
        trips=trips,
        selected_trip_id=selected_trip_id,
        content_template="partials/item_form.html",
        trip_list_error=trip_list_error,
        status_code=status_code,
        page_error=form_error,
        form_errors_by_field=error_details_by_field(form_error),
        form_title=form_title,
        form_description=form_description,
        form_action=form_action,
        submit_label=submit_label,
        cancel_url=cancel_url,
        item_form=item_form,
        show_id_field=show_id_field,
        trip=trip,
    )


def render_confirmation_screen(
    request: Request,
    *,
    trips: list[TripRecord],
    selected_trip_id: str | None,
    trip_list_error: ApiError | None,
    title: str,
    description: str,
    confirm_action: str,
    confirm_label: str,
    cancel_url: str,
    hidden_fields: dict[str, str],
    form_error: ApiError | None = None,
    status_code: int = 200,
) -> Response:
    return render_screen(
        request,
        page_title=title,
        trips=trips,
        selected_trip_id=selected_trip_id,
        content_template="partials/delete_confirmation.html",
        trip_list_error=trip_list_error,
        status_code=status_code,
        page_error=form_error,
        title=title,
        description=description,
        confirm_action=confirm_action,
        confirm_label=confirm_label,
        cancel_url=cancel_url,
        hidden_fields=hidden_fields,
    )


def render_trip_detail_screen(
    request: Request,
    *,
    trip: TripDetail,
    trips: list[TripRecord],
    trip_list_error: ApiError | None,
    selected_date: str | None = None,
    category_value: str | None = None,
    page_error: ApiError | None = None,
    status_code: int = 200,
    push_url: str | None = None,
) -> Response:
    display_days, filter_error = validate_filter_state(
        trip,
        selected_date=selected_date,
        category_value=category_value,
    )
    effective_error = page_error or filter_error
    effective_status = status_code
    if page_error is None and filter_error is not None and status_code == 200:
        effective_status = filter_error.status_code

    return render_screen(
        request,
        page_title=trip.name,
        trips=trips,
        selected_trip_id=trip.id,
        content_template="partials/trip_detail.html",
        trip_list_error=trip_list_error,
        status_code=effective_status,
        push_url=push_url,
        page_error=effective_error,
        filter_errors_by_field=error_details_by_field(filter_error),
        trip=trip,
        display_days=display_days,
        filter_state={
            "date": selected_date or "",
            "category": category_value or "",
        },
        selected_date=selected_date,
        add_item_date=selected_date or trip.start_date,
    )


def backend_dependency_from_error(error: ApiError) -> DependencyStatus:
    status_map = {
        "DEPENDENCY_TIMEOUT": "timeout",
        "DEPENDENCY_UNAVAILABLE": "unavailable",
        "BAD_GATEWAY": "invalid_response",
    }
    return DependencyStatus(
        status=status_map.get(error.code, "unavailable"),
        service="student-1-backend",
        detail=error.message,
        code=error.code,
    )


def backend_dependency_from_payload(
    payload_status: str, payload_service: str
) -> DependencyStatus:
    lowered = payload_status.lower()
    if lowered == "ok":
        return DependencyStatus(
            status="ok",
            service=payload_service,
            detail="Backend API responded successfully.",
        )

    if lowered == "unavailable":
        return DependencyStatus(
            status="unavailable",
            service=payload_service,
            detail="Backend API reported it is not ready yet.",
        )

    return DependencyStatus(
        status="degraded",
        service=payload_service,
        detail=f"Backend API reported status '{payload_status}'.",
    )


def probe_backend_health(client: BackendApiClient) -> DependencyStatus:
    try:
        payload = client.health()
    except ApiError as exc:
        return backend_dependency_from_error(exc)

    return backend_dependency_from_payload(payload.status, payload.service)


def probe_backend_ready(client: BackendApiClient) -> DependencyStatus:
    try:
        payload = client.ready()
    except ApiError as exc:
        return backend_dependency_from_error(exc)

    return backend_dependency_from_payload(payload.status, payload.service)


def trip_delete_description(trip_name: str) -> str:
    return (
        f"Delete '{trip_name}'? This removes the trip and all itinerary items "
        "for the selected dates."
    )


def item_delete_description(item_title: str, item_date: str) -> str:
    return (
        f"Delete '{item_title}' from {item_date}? This cannot be undone from "
        "the browser."
    )


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = BackendApiClient(app_settings, transport=transport)
        app.state.backend_client = client
        try:
            yield
        finally:
            client.close()

    app = FastAPI(
        title="TripGenie Student 1 Frontend",
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

    @app.get(
        "/health",
        response_model=DataEnvelope[HealthResponse],
    )
    def health(
        client: BackendApiClient = Depends(get_backend_client),
    ) -> dict[str, object]:
        backend = probe_backend_health(client)
        status = "ok" if backend.status == "ok" else "degraded"
        return envelope(
            HealthResponse(
                status=status,
                service=app_settings.service_name,
                dependencies=FrontendHealthDependencies(backend=backend),
            ).model_dump(mode="json"),
        )

    @app.get(
        "/ready",
        response_model=DataEnvelope[HealthResponse],
        responses={503: {"model": DataEnvelope[HealthResponse]}},
    )
    def ready(
        response: Response,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> dict[str, object]:
        backend = probe_backend_ready(client)
        is_ready = backend.status == "ok"
        if not is_ready:
            response.status_code = 503
        return envelope(
            HealthResponse(
                status="ok" if is_ready else "unavailable",
                service=app_settings.service_name,
                dependencies=FrontendHealthDependencies(backend=backend),
            ).model_dump(mode="json"),
        )

    @app.get("/", name="dashboard")
    def dashboard(
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        if trip_list_error is not None:
            return render_error_screen(
                request,
                error=trip_list_error,
                error_title="Student 1 trips are unavailable",
                page_title="Student 1 trips unavailable",
                trips=trips,
                trip_list_error=trip_list_error,
                retry_url=path_for(request, "dashboard"),
            )

        if not trips:
            return render_home_screen(
                request,
                trips=trips,
                trip_list_error=None,
            )

        selected_trip_id = trips[0].id
        try:
            trip = client.get_trip(selected_trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to load the selected trip",
                page_title="Selected trip unavailable",
                trips=trips,
                selected_trip_id=selected_trip_id,
                retry_url=path_for(request, "view_trip", trip_id=selected_trip_id),
                fallback_url=path_for(request, "dashboard"),
            )

        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=None,
        )

    @app.get("/trips/new", name="new_trip_form")
    def new_trip_form(
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        cancel_url = (
            path_for(request, "view_trip", trip_id=trips[0].id)
            if trips
            else path_for(request, "dashboard")
        )
        return render_trip_form_screen(
            request,
            trips=trips,
            selected_trip_id=None,
            trip_list_error=trip_list_error,
            form_title="Create trip",
            form_description=CREATE_TRIP_DESCRIPTION,
            form_action=path_for(request, "create_trip"),
            submit_label="Create trip",
            cancel_url=cancel_url,
            trip_form=empty_trip_form(),
            show_id_field=True,
        )

    @app.post("/trips", name="create_trip")
    async def create_trip(
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(
            request,
            (
                "id",
                "name",
                "destination",
                "start_date",
                "end_date",
                "traveller_count",
                "status",
                "notes",
            ),
        )
        payload = trip_payload_from_form(values, include_id=True)
        try:
            trip = client.create_trip(payload)
        except ApiError as exc:
            trips, trip_list_error = safe_list_trips(client)
            cancel_url = (
                path_for(request, "view_trip", trip_id=trips[0].id)
                if trips
                else path_for(request, "dashboard")
            )
            return render_trip_form_screen(
                request,
                trips=trips,
                selected_trip_id=None,
                trip_list_error=trip_list_error,
                form_title="Create trip",
                form_description=CREATE_TRIP_DESCRIPTION,
                form_action=path_for(request, "create_trip"),
                submit_label="Create trip",
                cancel_url=cancel_url,
                trip_form=values,
                form_error=exc,
                show_id_field=True,
                status_code=exc.status_code,
            )

        destination_url = path_for(request, "view_trip", trip_id=trip.id)
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        trips, trip_list_error = safe_list_trips(client)
        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            status_code=201,
            push_url=destination_url,
        )

    @app.get("/trips/{trip_id}", name="view_trip")
    def view_trip(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to load the selected trip",
                page_title="Selected trip unavailable",
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                retry_url=path_for(request, "view_trip", trip_id=trip_id),
                fallback_url=path_for(request, "dashboard"),
            )

        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            selected_date=normalise_optional_text(request.query_params.get("date")),
            category_value=normalise_optional_text(
                request.query_params.get("category")
            ),
        )

    @app.get("/trips/{trip_id}/days/{trip_day}", name="view_trip_day")
    def view_trip_day(
        trip_id: str,
        trip_day: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to load the selected trip day",
                page_title="Selected trip day unavailable",
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                retry_url=path_for(
                    request, "view_trip_day", trip_id=trip_id, trip_day=trip_day
                ),
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            selected_date=trip_day,
            category_value=normalise_optional_text(
                request.query_params.get("category")
            ),
        )

    @app.get("/trips/{trip_id}/edit", name="edit_trip_form")
    def edit_trip_form(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to open the trip edit form",
                page_title="Trip edit unavailable",
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                retry_url=path_for(request, "edit_trip_form", trip_id=trip_id),
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        return render_trip_form_screen(
            request,
            trips=trips,
            selected_trip_id=trip_id,
            trip_list_error=trip_list_error,
            form_title="Edit trip",
            form_description=EDIT_TRIP_DESCRIPTION,
            form_action=path_for(request, "update_trip", trip_id=trip_id),
            submit_label="Save trip changes",
            cancel_url=path_for(request, "view_trip", trip_id=trip_id),
            trip_form=trip_form_from_record(trip),
        )

    @app.post("/trips/{trip_id}/edit", name="update_trip")
    async def update_trip(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(
            request,
            (
                "name",
                "destination",
                "start_date",
                "end_date",
                "traveller_count",
                "status",
                "notes",
            ),
        )
        try:
            trip = client.update_trip(
                trip_id, trip_payload_from_form({"id": "", **values}, include_id=False)
            )
        except ApiError as exc:
            trips, trip_list_error = safe_list_trips(client)
            return render_trip_form_screen(
                request,
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                form_title="Edit trip",
                form_description=EDIT_TRIP_DESCRIPTION,
                form_action=path_for(request, "update_trip", trip_id=trip_id),
                submit_label="Save trip changes",
                cancel_url=path_for(request, "view_trip", trip_id=trip_id),
                trip_form={"id": trip_id, **values},
                form_error=exc,
                status_code=exc.status_code,
            )

        destination_url = path_for(request, "view_trip", trip_id=trip.id)
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        trips, trip_list_error = safe_list_trips(client)
        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            push_url=destination_url,
        )

    @app.get("/trips/{trip_id}/delete", name="delete_trip_confirmation")
    def delete_trip_confirmation(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to open trip deletion",
                page_title="Trip deletion unavailable",
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                retry_url=path_for(
                    request, "delete_trip_confirmation", trip_id=trip_id
                ),
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        return render_confirmation_screen(
            request,
            trips=trips,
            selected_trip_id=trip_id,
            trip_list_error=trip_list_error,
            title="Delete trip",
            description=trip_delete_description(trip.name),
            confirm_action=path_for(request, "delete_trip", trip_id=trip_id),
            confirm_label="Delete trip",
            cancel_url=path_for(request, "view_trip", trip_id=trip_id),
            hidden_fields={"trip_name": trip.name},
        )

    @app.post("/trips/{trip_id}/delete", name="delete_trip")
    async def delete_trip(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(request, ("trip_name",))
        try:
            client.delete_trip(trip_id)
        except ApiError as exc:
            trips, trip_list_error = safe_list_trips(client)
            return render_confirmation_screen(
                request,
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                title="Delete trip",
                description=trip_delete_description(values["trip_name"] or trip_id),
                confirm_action=path_for(request, "delete_trip", trip_id=trip_id),
                confirm_label="Delete trip",
                cancel_url=path_for(request, "view_trip", trip_id=trip_id),
                hidden_fields=values,
                form_error=exc,
                status_code=exc.status_code,
            )

        trips, trip_list_error = safe_list_trips(client)
        if trips:
            destination_url = path_for(request, "view_trip", trip_id=trips[0].id)
            if not is_htmx_request(request):
                return RedirectResponse(destination_url, status_code=303)

            try:
                trip = client.get_trip(trips[0].id)
            except ApiError as exc:
                return render_error_screen(
                    request,
                    error=exc,
                    error_title="Trip deleted, but the next trip could not be loaded",
                    page_title="Next trip unavailable",
                    trips=trips,
                    selected_trip_id=trips[0].id,
                    trip_list_error=trip_list_error,
                    retry_url=destination_url,
                    fallback_url=path_for(request, "dashboard"),
                )

            return render_trip_detail_screen(
                request,
                trip=trip,
                trips=trips,
                trip_list_error=trip_list_error,
                push_url=destination_url,
            )

        destination_url = path_for(request, "dashboard")
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        return render_home_screen(
            request,
            trips=trips,
            trip_list_error=trip_list_error,
            push_url=destination_url,
        )

    @app.get("/trips/{trip_id}/items/new", name="new_item_form")
    def new_item_form(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to open the itinerary form",
                page_title="Itinerary form unavailable",
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                retry_url=path_for(request, "new_item_form", trip_id=trip_id),
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        requested_date = normalise_optional_text(request.query_params.get("date"))
        cancel_date = iso_date_or_none(requested_date)
        cancel_url = (
            path_for(request, "view_trip_day", trip_id=trip_id, trip_day=cancel_date)
            if cancel_date is not None
            else path_for(request, "view_trip", trip_id=trip_id)
        )
        return render_item_form_screen(
            request,
            trip=trip,
            trips=trips,
            selected_trip_id=trip_id,
            trip_list_error=trip_list_error,
            form_title="Add itinerary item",
            form_description=CREATE_ITEM_DESCRIPTION,
            form_action=path_for(request, "create_item", trip_id=trip_id),
            submit_label="Add itinerary item",
            cancel_url=cancel_url,
            item_form=empty_item_form(requested_date or trip.start_date),
            show_id_field=True,
        )

    @app.post("/trips/{trip_id}/items", name="create_item")
    async def create_item(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(
            request,
            (
                "id",
                "date",
                "start_time",
                "end_time",
                "title",
                "location",
                "description",
                "category",
                "notes",
            ),
        )
        try:
            created_item = client.create_itinerary_item(
                trip_id,
                item_payload_from_form(values, include_id=True),
            )
        except ApiError as exc:
            trips, trip_list_error = safe_list_trips(client)
            try:
                trip = client.get_trip(trip_id)
            except ApiError as trip_exc:
                return render_error_screen(
                    request,
                    error=trip_exc,
                    error_title=RECOVER_TRIP_AFTER_ITEM_ERROR,
                    page_title="Trip unavailable",
                    trips=trips,
                    selected_trip_id=trip_id,
                    trip_list_error=trip_list_error,
                    retry_url=path_for(request, "new_item_form", trip_id=trip_id),
                    fallback_url=path_for(request, "view_trip", trip_id=trip_id),
                )

            cancel_date = iso_date_or_none(values["date"])
            cancel_url = (
                path_for(
                    request, "view_trip_day", trip_id=trip_id, trip_day=cancel_date
                )
                if cancel_date is not None
                else path_for(request, "view_trip", trip_id=trip_id)
            )
            return render_item_form_screen(
                request,
                trip=trip,
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                form_title="Add itinerary item",
                form_description=CREATE_ITEM_DESCRIPTION,
                form_action=path_for(request, "create_item", trip_id=trip_id),
                submit_label="Add itinerary item",
                cancel_url=cancel_url,
                item_form=values,
                form_error=exc,
                show_id_field=True,
                status_code=exc.status_code,
            )

        destination_url = path_for(
            request,
            "view_trip_day",
            trip_id=trip_id,
            trip_day=created_item.date,
        )
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Item created, but the trip could not be reloaded",
                page_title="Trip unavailable",
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                retry_url=destination_url,
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            selected_date=created_item.date,
            push_url=destination_url,
        )

    @app.get("/items/{item_id}/edit", name="edit_item_form")
    def edit_item_form(
        item_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            item = client.get_itinerary_item(item_id)
            trip = client.get_trip(item.trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to open the itinerary edit form",
                page_title="Itinerary edit unavailable",
                trips=trips,
                trip_list_error=trip_list_error,
                retry_url=path_for(request, "edit_item_form", item_id=item_id),
                fallback_url=path_for(request, "dashboard"),
            )

        return render_item_form_screen(
            request,
            trip=trip,
            trips=trips,
            selected_trip_id=item.trip_id,
            trip_list_error=trip_list_error,
            form_title="Edit itinerary item",
            form_description=EDIT_ITEM_DESCRIPTION,
            form_action=path_for(request, "update_item", item_id=item_id),
            submit_label="Save itinerary changes",
            cancel_url=path_for(
                request, "view_trip_day", trip_id=item.trip_id, trip_day=item.date
            ),
            item_form=item_form_from_record(item),
        )

    @app.post("/items/{item_id}/edit", name="update_item")
    async def update_item(
        item_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(
            request,
            (
                "trip_id",
                "date",
                "start_time",
                "end_time",
                "title",
                "location",
                "description",
                "category",
                "notes",
            ),
        )
        trip_id = values["trip_id"].strip()
        item_form = {
            "id": item_id,
            "date": values["date"],
            "start_time": values["start_time"],
            "end_time": values["end_time"],
            "title": values["title"],
            "location": values["location"],
            "description": values["description"],
            "category": values["category"],
            "notes": values["notes"],
        }
        try:
            updated_item = client.update_itinerary_item(
                item_id,
                item_payload_from_form(item_form, include_id=False),
            )
        except ApiError as exc:
            trips, trip_list_error = safe_list_trips(client)
            try:
                trip = client.get_trip(trip_id)
            except ApiError as trip_exc:
                return render_error_screen(
                    request,
                    error=trip_exc,
                    error_title=RECOVER_TRIP_AFTER_ITEM_ERROR,
                    page_title="Trip unavailable",
                    trips=trips,
                    selected_trip_id=trip_id or None,
                    trip_list_error=trip_list_error,
                    retry_url=path_for(request, "edit_item_form", item_id=item_id),
                    fallback_url=path_for(request, "dashboard"),
                )

            cancel_date = iso_date_or_none(values["date"])
            cancel_url = (
                path_for(
                    request, "view_trip_day", trip_id=trip_id, trip_day=cancel_date
                )
                if cancel_date is not None
                else path_for(request, "view_trip", trip_id=trip_id)
            )
            return render_item_form_screen(
                request,
                trip=trip,
                trips=trips,
                selected_trip_id=trip_id,
                trip_list_error=trip_list_error,
                form_title="Edit itinerary item",
                form_description=EDIT_ITEM_DESCRIPTION,
                form_action=path_for(request, "update_item", item_id=item_id),
                submit_label="Save itinerary changes",
                cancel_url=cancel_url,
                item_form=item_form,
                form_error=exc,
                status_code=exc.status_code,
            )

        destination_url = path_for(
            request,
            "view_trip_day",
            trip_id=updated_item.trip_id,
            trip_day=updated_item.date,
        )
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(updated_item.trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Item updated, but the trip could not be reloaded",
                page_title="Trip unavailable",
                trips=trips,
                selected_trip_id=updated_item.trip_id,
                trip_list_error=trip_list_error,
                retry_url=destination_url,
                fallback_url=path_for(
                    request, "view_trip", trip_id=updated_item.trip_id
                ),
            )

        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            selected_date=updated_item.date,
            push_url=destination_url,
        )

    @app.get("/items/{item_id}/delete", name="delete_item_confirmation")
    def delete_item_confirmation(
        item_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = safe_list_trips(client)
        try:
            item = client.get_itinerary_item(item_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to open itinerary deletion",
                page_title="Itinerary deletion unavailable",
                trips=trips,
                trip_list_error=trip_list_error,
                retry_url=path_for(
                    request, "delete_item_confirmation", item_id=item_id
                ),
                fallback_url=path_for(request, "dashboard"),
            )

        return render_confirmation_screen(
            request,
            trips=trips,
            selected_trip_id=item.trip_id,
            trip_list_error=trip_list_error,
            title="Delete itinerary item",
            description=item_delete_description(item.title, item.date),
            confirm_action=path_for(request, "delete_item", item_id=item_id),
            confirm_label="Delete itinerary item",
            cancel_url=path_for(
                request, "view_trip_day", trip_id=item.trip_id, trip_day=item.date
            ),
            hidden_fields={
                "trip_id": item.trip_id,
                "item_date": item.date,
                "item_title": item.title,
            },
        )

    @app.post("/items/{item_id}/delete", name="delete_item")
    async def delete_item(
        item_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(request, ("trip_id", "item_date", "item_title"))
        trip_id = values["trip_id"].strip()
        item_date = values["item_date"].strip()
        try:
            client.delete_itinerary_item(item_id)
        except ApiError as exc:
            trips, trip_list_error = safe_list_trips(client)
            cancel_url = (
                path_for(request, "view_trip_day", trip_id=trip_id, trip_day=item_date)
                if trip_id and item_date
                else path_for(request, "dashboard")
            )
            return render_confirmation_screen(
                request,
                trips=trips,
                selected_trip_id=trip_id or None,
                trip_list_error=trip_list_error,
                title="Delete itinerary item",
                description=item_delete_description(
                    values["item_title"] or item_id,
                    item_date or "the selected day",
                ),
                confirm_action=path_for(request, "delete_item", item_id=item_id),
                confirm_label="Delete itinerary item",
                cancel_url=cancel_url,
                hidden_fields=values,
                form_error=exc,
                status_code=exc.status_code,
            )

        destination_url = (
            path_for(request, "view_trip_day", trip_id=trip_id, trip_day=item_date)
            if trip_id and item_date
            else path_for(request, "dashboard")
        )
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        trips, trip_list_error = safe_list_trips(client)
        try:
            trip = client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Item deleted, but the trip could not be reloaded",
                page_title="Trip unavailable",
                trips=trips,
                selected_trip_id=trip_id or None,
                trip_list_error=trip_list_error,
                retry_url=destination_url,
                fallback_url=path_for(request, "dashboard"),
            )

        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            selected_date=item_date,
            push_url=destination_url,
        )

    return app


app = create_app()
