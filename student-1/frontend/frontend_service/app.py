from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .client import BackendApiClient
from .config import Settings
from .errors import ApiError, validation_error
from .models import (
    AiSuggestionDraft,
    AiSuggestionReviewPayload,
    AiSuggestionsResponse,
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
AI_MODE_DESCRIPTION = (
    "Request draft itinerary suggestions for one trip day, then review and "
    "save each draft through the normal CRUD form."
)
AI_REVIEW_NOTICE = (
    "You are reviewing an AI-generated draft. Edit anything needed before "
    "saving it as a normal itinerary item."
)
AI_REVIEW_PREPARATION_ERROR = "The AI draft could not be prepared for review."
RECOVER_TRIP_AFTER_ITEM_ERROR = (
    "Unable to recover the trip after itinerary validation failed"
)
INVALID_DATE_ISSUE = "must be a valid ISO date in YYYY-MM-DD format"
ITEM_FORM_DEFAULT_DATE_MESSAGE = (
    "The requested itinerary date could not be applied. The form defaulted to "
    "the trip start date."
)
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


@dataclass(slots=True)
class DateFilterResolution:
    raw_value: str
    selected_date: str | None
    error: ApiError | None


@dataclass(slots=True)
class AiSuggestionReviewCard:
    draft: AiSuggestionDraft
    review_action: str
    review_payload: str


@dataclass(slots=True)
class AiSuggestionResultView:
    requested_date: str
    model: str
    prompt_asset: str
    run_id: str
    correlation_id: str
    attempt_count: int
    approval_required: bool
    persisted: bool
    suggestions: list[AiSuggestionReviewCard]


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


async def safe_list_trips(
    client: BackendApiClient,
) -> tuple[list[TripRecord], ApiError | None]:
    try:
        return await client.list_trips(), None
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


def empty_ai_form(date_value: str = "") -> dict[str, str]:
    return {
        "requested_date": date_value,
        "goal": "",
        "interests": "",
        "constraints": "",
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


def item_form_from_ai_review_payload(
    payload: AiSuggestionReviewPayload,
) -> dict[str, str]:
    return {
        "id": "",
        "date": payload.date,
        "start_time": payload.start_time or "",
        "end_time": payload.end_time or "",
        "title": payload.title,
        "location": payload.location or "",
        "description": payload.description or "",
        "category": payload.category.value,
        "notes": payload.notes or "",
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


def ai_payload_from_form(values: dict[str, str]) -> dict[str, object]:
    return {
        "requested_date": values["requested_date"].strip(),
        "goal": values["goal"].strip(),
        "interests": normalise_optional_text(values["interests"]),
        "constraints": normalise_optional_text(values["constraints"]),
    }


def iso_date_or_none(value: str | None) -> str | None:
    cleaned = normalise_optional_text(value)
    if cleaned is None:
        return None

    try:
        if ISO_DATE_PATTERN.fullmatch(cleaned) is None:
            raise ValueError
        date.fromisoformat(cleaned)
    except ValueError:
        return None

    return cleaned


def iso_time_or_none(value: str | None) -> str | None:
    cleaned = normalise_optional_text(value)
    if cleaned is None:
        return None

    try:
        if ISO_TIME_PATTERN.fullmatch(cleaned) is None:
            raise ValueError
        parsed = time.fromisoformat(cleaned)
        if parsed.second or parsed.microsecond:
            raise ValueError
    except ValueError:
        return None

    return cleaned


def trip_date_range_issue(trip: TripDetail) -> str:
    return f"must fall between {trip.start_date} and {trip.end_date}"


def resolve_filter_date(
    trip: TripDetail,
    requested_date: str | None,
) -> DateFilterResolution:
    cleaned = normalise_optional_text(requested_date) or ""
    if not cleaned:
        return DateFilterResolution(raw_value="", selected_date=None, error=None)

    try:
        if ISO_DATE_PATTERN.fullmatch(cleaned) is None:
            raise ValueError
        date.fromisoformat(cleaned)
    except ValueError:
        return DateFilterResolution(
            raw_value=cleaned,
            selected_date=None,
            error=validation_error(
                "Select a valid trip date.",
                [{"field": "date", "issue": INVALID_DATE_ISSUE}],
            ),
        )

    if cleaned < trip.start_date or cleaned > trip.end_date:
        return DateFilterResolution(
            raw_value=cleaned,
            selected_date=None,
            error=validation_error(
                "Select a date within the trip window.",
                [{"field": "date", "issue": trip_date_range_issue(trip)}],
            ),
        )

    return DateFilterResolution(raw_value=cleaned, selected_date=cleaned, error=None)


def build_query_url(
    base_url: str,
    *,
    date_value: str | None = None,
    category_value: str | None = None,
) -> str:
    query_items: list[tuple[str, str]] = []
    cleaned_date = normalise_optional_text(date_value)
    cleaned_category = normalise_optional_text(category_value)

    if cleaned_date:
        query_items.append(("date", cleaned_date))
    if cleaned_category:
        query_items.append(("category", cleaned_category))

    if not query_items:
        return base_url

    return f"{base_url}?{urlencode(query_items)}"


def item_form_query_error(
    *,
    trip: TripDetail,
    date_error: ApiError,
) -> ApiError:
    return validation_error(
        (
            f"{ITEM_FORM_DEFAULT_DATE_MESSAGE} Using {trip.start_date} until a "
            "valid in-range date is selected."
        ),
        date_error.details,
    )


def item_cancel_url(
    request: Request,
    *,
    trip_id: str,
    trip: TripDetail,
    requested_date: str | None,
) -> str:
    date_resolution = resolve_filter_date(trip, requested_date)
    if date_resolution.selected_date is None:
        return path_for(request, "view_trip", trip_id=trip_id)

    return path_for(
        request,
        "view_trip_day",
        trip_id=trip_id,
        trip_day=date_resolution.selected_date,
    )


def validate_filter_state(
    trip: TripDetail,
    *,
    selected_date: str | None,
    category_value: str | None,
) -> tuple[list[TripDay], ApiError | None, DateFilterResolution]:
    date_resolution = resolve_filter_date(trip, selected_date)
    display_days = trip.days
    if date_resolution.selected_date is not None:
        matching_days = [
            day for day in trip.days if day.date == date_resolution.selected_date
        ]
        display_days = matching_days or [
            TripDay(date=date_resolution.selected_date, items=[])
        ]

    if category_value:
        try:
            category = ItineraryCategory(category_value)
        except ValueError:
            return (
                display_days,
                validation_error(
                    "Select a supported itinerary category.",
                    [
                        {
                            "field": "category",
                            "issue": f"must be one of: {CATEGORY_VALUE_LIST}",
                        },
                    ],
                ),
                date_resolution,
            )

        filtered_days: list[TripDay] = []
        for day in display_days:
            filtered_items = [item for item in day.items if item.category == category]
            if date_resolution.selected_date is not None:
                filtered_days.append(TripDay(date=day.date, items=filtered_items))
            elif filtered_items:
                filtered_days.append(TripDay(date=day.date, items=filtered_items))

        display_days = filtered_days

    return display_days, date_resolution.error, date_resolution


def build_ai_review_payload(suggestion: AiSuggestionDraft) -> str:
    return json.dumps(
        {
            "date": suggestion.date,
            "start_time": suggestion.start_time,
            "end_time": suggestion.end_time,
            "title": suggestion.title,
            "location": suggestion.location,
            "description": suggestion.description,
            "category": suggestion.category.value,
            "notes": suggestion.notes,
            "ai_rationale": suggestion.rationale,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_ai_result_view(
    request: Request,
    *,
    trip_id: str,
    result: AiSuggestionsResponse,
) -> AiSuggestionResultView:
    return AiSuggestionResultView(
        requested_date=result.requested_date,
        model=result.model,
        prompt_asset=result.prompt_asset,
        run_id=result.run_id,
        correlation_id=result.correlation_id,
        attempt_count=result.attempt_count,
        approval_required=result.approval_required,
        persisted=result.persisted,
        suggestions=[
            AiSuggestionReviewCard(
                draft=suggestion,
                review_action=path_for(request, "new_item_form", trip_id=trip_id),
                review_payload=build_ai_review_payload(suggestion),
            )
            for suggestion in result.suggestions
        ],
    )


def prefilled_item_form_from_query(
    request: Request,
    *,
    trip: TripDetail,
) -> tuple[dict[str, str], ApiError | None, str | None, str | None]:
    requested_date = normalise_optional_text(request.query_params.get("date"))
    date_resolution = resolve_filter_date(trip, requested_date)
    form_error = (
        item_form_query_error(trip=trip, date_error=date_resolution.error)
        if date_resolution.error is not None
        else None
    )

    return (
        empty_item_form(date_resolution.selected_date or trip.start_date),
        form_error,
        None,
        None,
    )


def _validation_detail_field(
    location: tuple[object, ...],
    *,
    fallback: str,
) -> str:
    filtered = [str(part) for part in location if part not in {"body", "query", "path"}]
    if filtered:
        return ".".join(filtered)
    return fallback


def _validation_detail_issue(message: str) -> str:
    if message.startswith("Value error, "):
        return message.removeprefix("Value error, ")
    return message


def ai_review_error_from_validation(exc: ValidationError) -> ApiError:
    details: list[dict[str, str]] = []
    for error in exc.errors():
        if error["type"] == "json_invalid":
            details.append(
                {
                    "field": "ai_review",
                    "issue": "must contain a valid AI draft payload",
                }
            )
            continue

        details.append(
            {
                "field": _validation_detail_field(
                    tuple(error["loc"]),
                    fallback="ai_review",
                ),
                "issue": _validation_detail_issue(str(error["msg"])),
            }
        )

    return validation_error(AI_REVIEW_PREPARATION_ERROR, details)


def prefilled_item_form_from_ai_review(
    draft_payload: str,
    *,
    trip: TripDetail,
) -> tuple[dict[str, str], ApiError | None, str | None, str | None]:
    if not draft_payload.strip():
        return (
            empty_item_form(trip.start_date),
            validation_error(
                AI_REVIEW_PREPARATION_ERROR,
                [
                    {
                        "field": "ai_review",
                        "issue": "must contain a valid AI draft payload",
                    }
                ],
            ),
            AI_REVIEW_NOTICE,
            None,
        )

    try:
        payload = AiSuggestionReviewPayload.model_validate_json(draft_payload)
    except ValidationError as exc:
        return (
            empty_item_form(trip.start_date),
            ai_review_error_from_validation(exc),
            AI_REVIEW_NOTICE,
            None,
        )

    date_resolution = resolve_filter_date(trip, payload.date)
    form_error = None
    if date_resolution.error is not None:
        form_error = validation_error(
            AI_REVIEW_PREPARATION_ERROR,
            date_resolution.error.details,
        )

    return (
        item_form_from_ai_review_payload(payload),
        form_error,
        AI_REVIEW_NOTICE,
        normalise_optional_text(payload.ai_rationale),
    )


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
    ai_review_notice: str | None = None,
    ai_review_rationale: str | None = None,
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
        ai_review_notice=ai_review_notice,
        ai_review_rationale=ai_review_rationale,
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
    ai_form: dict[str, str] | None = None,
    ai_error: ApiError | None = None,
    ai_result: AiSuggestionResultView | None = None,
) -> Response:
    display_days, filter_error, date_resolution = validate_filter_state(
        trip,
        selected_date=selected_date,
        category_value=category_value,
    )
    effective_error = page_error or filter_error
    effective_status = status_code
    if page_error is None and filter_error is not None and status_code == 200:
        effective_status = filter_error.status_code

    effective_ai_form = ai_form or empty_ai_form(
        date_resolution.selected_date or trip.start_date,
    )

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
            "date": date_resolution.raw_value,
            "category": category_value or "",
        },
        selected_date=date_resolution.selected_date,
        add_item_date=date_resolution.selected_date or trip.start_date,
        ai_form=effective_ai_form,
        ai_error=ai_error,
        ai_errors_by_field=error_details_by_field(ai_error),
        ai_result=ai_result,
        # Browser-facing, so a row can link out to student 2's own page.
        accommodation_ui_url=request.app.state.settings.accommodation_ui_url,
    )


def accommodation_remove_description(name: str, trip_name: str) -> str:
    return (
        f"Remove {name} from {trip_name}? The accommodation itself is not "
        "deleted -- only its place on this trip."
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


async def probe_backend_health(client: BackendApiClient) -> DependencyStatus:
    try:
        payload = await client.health()
    except ApiError as exc:
        return backend_dependency_from_error(exc)

    return backend_dependency_from_payload(payload.status, payload.service)


async def probe_backend_ready(client: BackendApiClient) -> DependencyStatus:
    try:
        payload = await client.ready()
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
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = BackendApiClient(app_settings, transport=transport)
        app.state.backend_client = client
        app.state.settings = app_settings
        try:
            yield
        finally:
            await client.close()

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
    async def health(
        client: BackendApiClient = Depends(get_backend_client),
    ) -> dict[str, object]:
        backend = await probe_backend_health(client)
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
    async def ready(
        response: Response,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> dict[str, object]:
        backend = await probe_backend_ready(client)
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
    async def dashboard(
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
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
            trip = await client.get_trip(selected_trip_id)
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
    async def new_trip_form(
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
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
            trip = await client.create_trip(payload)
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
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

        trips, trip_list_error = await safe_list_trips(client)
        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            status_code=201,
            push_url=destination_url,
        )

    @app.get("/trips/{trip_id}", name="view_trip")
    async def view_trip(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        selected_date = normalise_optional_text(request.query_params.get("date"))
        category_value = normalise_optional_text(request.query_params.get("category"))
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
            selected_date=selected_date,
            category_value=category_value,
            push_url=build_query_url(
                path_for(request, "view_trip", trip_id=trip_id),
                date_value=selected_date,
                category_value=category_value,
            ),
        )

    @app.get("/trips/{trip_id}/days/{trip_day}", name="view_trip_day")
    async def view_trip_day(
        trip_id: str,
        trip_day: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        category_value = normalise_optional_text(request.query_params.get("category"))
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
            category_value=category_value,
            push_url=build_query_url(
                path_for(
                    request,
                    "view_trip_day",
                    trip_id=trip_id,
                    trip_day=trip_day,
                ),
                category_value=category_value,
            ),
        )

    @app.post("/trips/{trip_id}/ai-suggestions", name="generate_ai_suggestions")
    async def generate_ai_suggestions(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(
            request,
            (
                "requested_date",
                "goal",
                "interests",
                "constraints",
                "view_date",
                "view_category",
            ),
        )
        selected_date = normalise_optional_text(values["view_date"])
        category_value = normalise_optional_text(values["view_category"])
        trips, trip_list_error = await safe_list_trips(client)
        try:
            result = await client.generate_ai_suggestions(
                trip_id,
                ai_payload_from_form(values),
            )
        except ApiError as exc:
            try:
                trip = await client.get_trip(trip_id)
            except ApiError as trip_exc:
                return render_error_screen(
                    request,
                    error=trip_exc,
                    error_title="Unable to reload the trip after the AI request failed",
                    page_title="Trip unavailable",
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
                selected_date=selected_date,
                category_value=category_value,
                status_code=exc.status_code,
                ai_form={
                    "requested_date": values["requested_date"],
                    "goal": values["goal"],
                    "interests": values["interests"],
                    "constraints": values["constraints"],
                },
                ai_error=exc,
                push_url=build_query_url(
                    path_for(request, "view_trip", trip_id=trip_id),
                    date_value=selected_date,
                    category_value=category_value,
                ),
            )

        try:
            trip = await client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title=(
                    "Suggestions were generated, but the trip could not be reloaded"
                ),
                page_title="Trip unavailable",
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
            selected_date=selected_date,
            category_value=category_value,
            ai_form={
                "requested_date": values["requested_date"],
                "goal": values["goal"],
                "interests": values["interests"],
                "constraints": values["constraints"],
            },
            ai_result=build_ai_result_view(
                request,
                trip_id=trip_id,
                result=result,
            ),
            push_url=build_query_url(
                path_for(request, "view_trip", trip_id=trip_id),
                date_value=selected_date,
                category_value=category_value,
            ),
        )

    @app.get("/trips/{trip_id}/edit", name="edit_trip_form")
    async def edit_trip_form(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
            trip = await client.update_trip(
                trip_id, trip_payload_from_form({"id": "", **values}, include_id=False)
            )
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
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

        trips, trip_list_error = await safe_list_trips(client)
        return render_trip_detail_screen(
            request,
            trip=trip,
            trips=trips,
            trip_list_error=trip_list_error,
            push_url=destination_url,
        )

    @app.get("/trips/{trip_id}/delete", name="delete_trip_confirmation")
    async def delete_trip_confirmation(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
            await client.delete_trip(trip_id)
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
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

        trips, trip_list_error = await safe_list_trips(client)
        if trips:
            destination_url = path_for(request, "view_trip", trip_id=trips[0].id)
            if not is_htmx_request(request):
                return RedirectResponse(destination_url, status_code=303)

            try:
                trip = await client.get_trip(trips[0].id)
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
    async def new_item_form(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
        item_form, form_error, ai_review_notice, ai_review_rationale = (
            prefilled_item_form_from_query(
                request,
                trip=trip,
            )
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
            cancel_url=item_cancel_url(
                request,
                trip_id=trip_id,
                trip=trip,
                requested_date=requested_date,
            ),
            item_form=item_form,
            form_error=form_error,
            show_id_field=True,
            status_code=form_error.status_code if form_error is not None else 200,
            ai_review_notice=ai_review_notice,
            ai_review_rationale=ai_review_rationale,
        )

    @app.post("/trips/{trip_id}/items/new", name="review_ai_item_form")
    async def review_ai_item_form(
        trip_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        values = await read_form_values(request, ("draft_payload",))
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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

        item_form, form_error, ai_review_notice, ai_review_rationale = (
            prefilled_item_form_from_ai_review(
                values["draft_payload"],
                trip=trip,
            )
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
            cancel_url=item_cancel_url(
                request,
                trip_id=trip_id,
                trip=trip,
                requested_date=item_form["date"],
            ),
            item_form=item_form,
            form_error=form_error,
            show_id_field=True,
            status_code=form_error.status_code if form_error is not None else 200,
            ai_review_notice=ai_review_notice,
            ai_review_rationale=ai_review_rationale,
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
                "ai_draft",
                "ai_rationale",
            ),
        )
        try:
            created_item = await client.create_itinerary_item(
                trip_id,
                item_payload_from_form(values, include_id=True),
            )
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
            try:
                trip = await client.get_trip(trip_id)
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
                cancel_url=item_cancel_url(
                    request,
                    trip_id=trip_id,
                    trip=trip,
                    requested_date=values["date"],
                ),
                item_form=values,
                form_error=exc,
                show_id_field=True,
                status_code=exc.status_code,
                ai_review_notice=(
                    AI_REVIEW_NOTICE
                    if values["ai_draft"].strip().lower() == "true"
                    else None
                ),
                ai_review_rationale=normalise_optional_text(values["ai_rationale"]),
            )

        destination_url = path_for(
            request,
            "view_trip_day",
            trip_id=trip_id,
            trip_day=created_item.date,
        )
        if not is_htmx_request(request):
            return RedirectResponse(destination_url, status_code=303)

        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
    async def edit_item_form(
        item_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
        try:
            item = await client.get_itinerary_item(item_id)
            trip = await client.get_trip(item.trip_id)
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
            updated_item = await client.update_itinerary_item(
                item_id,
                item_payload_from_form(item_form, include_id=False),
            )
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
            try:
                trip = await client.get_trip(trip_id)
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
                cancel_url=item_cancel_url(
                    request,
                    trip_id=trip_id,
                    trip=trip,
                    requested_date=values["date"],
                ),
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

        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(updated_item.trip_id)
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

    @app.get(
        "/trips/{trip_id}/accommodations/{accommodation_id}/remove",
        name="remove_accommodation_confirmation",
    )
    async def remove_accommodation_confirmation(
        trip_id: str,
        accommodation_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
        except ApiError as exc:
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to open accommodation removal",
                page_title="Accommodation removal unavailable",
                trips=trips,
                trip_list_error=trip_list_error,
                retry_url=path_for(
                    request,
                    "remove_accommodation_confirmation",
                    trip_id=trip_id,
                    accommodation_id=accommodation_id,
                ),
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        stay = next(
            (
                record
                for record in trip.accommodations
                if record.accommodation_id == accommodation_id
            ),
            None,
        )
        # The name is student 2's and may be missing; the id is always here.
        label = (stay.name if stay and stay.name else None) or accommodation_id
        return render_confirmation_screen(
            request,
            trips=trips,
            selected_trip_id=trip_id,
            trip_list_error=trip_list_error,
            title="Remove accommodation",
            description=accommodation_remove_description(label, trip.name),
            confirm_action=path_for(
                request,
                "remove_accommodation",
                trip_id=trip_id,
                accommodation_id=accommodation_id,
            ),
            confirm_label="Remove from trip",
            cancel_url=path_for(request, "view_trip", trip_id=trip_id),
            # Both ids are already in the POST path, so the form carries none.
            hidden_fields={},
        )

    @app.post(
        "/trips/{trip_id}/accommodations/{accommodation_id}/remove",
        name="remove_accommodation",
    )
    async def remove_accommodation(
        trip_id: str,
        accommodation_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        try:
            await client.remove_trip_accommodation(trip_id, accommodation_id)
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
            return render_error_screen(
                request,
                error=exc,
                error_title="Unable to remove accommodation",
                page_title="Accommodation removal failed",
                trips=trips,
                trip_list_error=trip_list_error,
                retry_url=path_for(
                    request,
                    "remove_accommodation_confirmation",
                    trip_id=trip_id,
                    accommodation_id=accommodation_id,
                ),
                fallback_url=path_for(request, "view_trip", trip_id=trip_id),
            )

        # Back to the trip, which is the thing that changed.
        return RedirectResponse(
            path_for(request, "view_trip", trip_id=trip_id),
            status_code=303,
        )

    @app.get("/items/{item_id}/delete", name="delete_item_confirmation")
    async def delete_item_confirmation(
        item_id: str,
        request: Request,
        client: BackendApiClient = Depends(get_backend_client),
    ) -> Response:
        trips, trip_list_error = await safe_list_trips(client)
        try:
            item = await client.get_itinerary_item(item_id)
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
            await client.delete_itinerary_item(item_id)
        except ApiError as exc:
            trips, trip_list_error = await safe_list_trips(client)
            cancel_url = path_for(request, "dashboard")
            if trip_id:
                try:
                    trip = await client.get_trip(trip_id)
                except ApiError:
                    cancel_url = path_for(request, "view_trip", trip_id=trip_id)
                else:
                    cancel_url = item_cancel_url(
                        request,
                        trip_id=trip_id,
                        trip=trip,
                        requested_date=item_date,
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

        trips, trip_list_error = await safe_list_trips(client)
        try:
            trip = await client.get_trip(trip_id)
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
