from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError, bad_request, validation_error
from .models import (
    DataEnvelope,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    HealthResponse,
    ItemIdentifier,
    ItineraryCategory,
    ItineraryItemCreate,
    ItineraryItemRecord,
    ItineraryItemUpdate,
    TripCreate,
    TripDaySelection,
    TripDetail,
    TripIdentifier,
    TripRecord,
    TripStatus,
    TripUpdate,
)
from .service import BackendService

VALIDATION_ERROR_MESSAGE = "One or more fields failed validation."
TRIP_STATUS_VALUES = ", ".join(status.value for status in TripStatus)
ITINERARY_CATEGORY_VALUES = ", ".join(category.value for category in ItineraryCategory)
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _error_response(exc: ApiError) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            details=[ErrorDetail(**detail) for detail in exc.details],
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
    )


def _validation_detail_field(location: tuple[object, ...]) -> str:
    filtered = [str(part) for part in location if part not in {"body", "query", "path"}]
    if filtered:
        return ".".join(filtered)

    return str(location[-1]) if location else "body"


def _ensure_allowed_query_params(request: Request, allowed: set[str]) -> None:
    extras = sorted(set(request.query_params) - allowed)
    if not extras:
        return

    raise bad_request(
        "Unsupported query parameters were provided.",
        [{"field": name, "issue": "is not supported"} for name in extras],
    )


def allow_query_params(*allowed: str):
    allowed_set = set(allowed)

    def dependency(request: Request) -> None:
        _ensure_allowed_query_params(request, allowed_set)

    return dependency


def get_service(request: Request) -> BackendService:
    return request.app.state.backend_service


def envelope(payload: object) -> dict[str, object]:
    return {"data": payload}


def _query_validation_details(field: str, issue: str) -> list[dict[str, str]]:
    return [{"field": field, "issue": issue}]


def _normalise_optional_query_text(
    value: str | None,
    *,
    field: str,
    max_length: int | None = None,
) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(field, "must not be blank"),
        )

    if max_length is not None and len(cleaned) > max_length:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(
                field,
                f"must be at most {max_length} characters",
            ),
        )

    return cleaned


def parse_trip_status_filter(
    status_value: Annotated[str | None, Query(alias="status")] = None,
) -> TripStatus | None:
    cleaned = _normalise_optional_query_text(status_value, field="status")
    if cleaned is None:
        return None

    try:
        return TripStatus(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(
                "status",
                f"must be one of: {TRIP_STATUS_VALUES}",
            ),
        ) from exc


def parse_destination_filter(
    destination_value: Annotated[str | None, Query(alias="destination")] = None,
) -> str | None:
    return _normalise_optional_query_text(
        destination_value,
        field="destination",
        max_length=255,
    )


def parse_date_filter(
    date_value: Annotated[str | None, Query(alias="date")] = None,
) -> str | None:
    cleaned = _normalise_optional_query_text(date_value, field="date")
    if cleaned is None:
        return None

    try:
        if ISO_DATE_PATTERN.fullmatch(cleaned) is None:
            raise ValueError
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(
                "date",
                "must be a valid ISO date in YYYY-MM-DD format",
            ),
        ) from exc

    return cleaned


def parse_category_filter(
    category_value: Annotated[str | None, Query(alias="category")] = None,
) -> ItineraryCategory | None:
    cleaned = _normalise_optional_query_text(category_value, field="category")
    if cleaned is None:
        return None

    try:
        return ItineraryCategory(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(
                "category",
                f"must be one of: {ITINERARY_CATEGORY_VALUES}",
            ),
        ) from exc


def parse_trip_day_path(
    trip_day: Annotated[str, Path(alias="trip_day")],
) -> str:
    cleaned = trip_day.strip()
    try:
        if ISO_DATE_PATTERN.fullmatch(cleaned) is None:
            raise ValueError
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(
                "date",
                "must be a valid ISO date in YYYY-MM-DD format",
            ),
        ) from exc

    return cleaned


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = DatabaseApiClient(app_settings, transport=transport)
        app.state.backend_service = BackendService(client, app_settings)
        try:
            yield
        finally:
            client.close()

    app = FastAPI(
        title="TripGenie Student 1 Backend API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "field": _validation_detail_field(tuple(error["loc"])),
                "issue": error["msg"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            ApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message=VALIDATION_ERROR_MESSAGE,
                details=details,
            ),
        )

    router = APIRouter(prefix=app_settings.api_prefix)
    no_query_params = Depends(allow_query_params())
    trip_query_params = Depends(allow_query_params("status", "destination"))
    item_query_params = Depends(allow_query_params("date", "category"))

    @app.get(
        "/health",
        dependencies=[no_query_params],
        response_model=DataEnvelope[HealthResponse],
    )
    def health(
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.health().model_dump(mode="json"))

    @app.get(
        "/ready",
        dependencies=[no_query_params],
        response_model=DataEnvelope[HealthResponse],
        responses={503: {"model": DataEnvelope[HealthResponse]}},
    )
    def ready(
        response: Response,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        status_code, payload = service.ready()
        response.status_code = status_code
        return envelope(payload.model_dump(mode="json"))

    @router.get(
        "/trips",
        dependencies=[trip_query_params],
        response_model=DataEnvelope[list[TripRecord]],
    )
    def list_trips(
        status_filter: Annotated[TripStatus | None, Depends(parse_trip_status_filter)],
        destination: Annotated[str | None, Depends(parse_destination_filter)],
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(
            service.list_trips(
                status=status_filter,
                destination=destination,
            ),
        )

    @router.post(
        "/trips",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TripDetail],
        status_code=status.HTTP_201_CREATED,
    )
    def create_trip(
        payload: TripCreate,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.create_trip(payload))

    @router.get(
        "/trips/{trip_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TripDetail],
    )
    def get_trip(
        trip_id: TripIdentifier,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.get_trip(trip_id))

    @router.get(
        "/trips/{trip_id}/days/{trip_day}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TripDaySelection],
    )
    def get_trip_day(
        trip_id: TripIdentifier,
        trip_day: Annotated[str, Depends(parse_trip_day_path)],
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.get_trip_day(trip_id, trip_day))

    @router.patch(
        "/trips/{trip_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TripDetail],
    )
    def update_trip(
        trip_id: TripIdentifier,
        payload: TripUpdate,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.update_trip(trip_id, payload))

    @router.delete(
        "/trips/{trip_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[dict[str, object]],
    )
    def delete_trip(
        trip_id: TripIdentifier,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.delete_trip(trip_id))

    @router.get(
        "/trips/{trip_id}/itinerary-items",
        dependencies=[item_query_params],
        response_model=DataEnvelope[list[ItineraryItemRecord]],
    )
    def list_itinerary_items(
        trip_id: TripIdentifier,
        date_filter: Annotated[str | None, Depends(parse_date_filter)],
        category_filter: Annotated[
            ItineraryCategory | None,
            Depends(parse_category_filter),
        ],
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(
            service.list_itinerary_items(
                trip_id,
                date=date_filter,
                category=category_filter,
            ),
        )

    @router.post(
        "/trips/{trip_id}/itinerary-items",
        dependencies=[no_query_params],
        response_model=DataEnvelope[ItineraryItemRecord],
        status_code=status.HTTP_201_CREATED,
    )
    def create_itinerary_item(
        trip_id: TripIdentifier,
        payload: ItineraryItemCreate,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.create_itinerary_item(trip_id, payload))

    @router.get(
        "/itinerary-items/{item_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[ItineraryItemRecord],
    )
    def get_itinerary_item(
        item_id: ItemIdentifier,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.get_itinerary_item(item_id))

    @router.patch(
        "/itinerary-items/{item_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[ItineraryItemRecord],
    )
    def update_itinerary_item(
        item_id: ItemIdentifier,
        payload: ItineraryItemUpdate,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.update_itinerary_item(item_id, payload))

    @router.delete(
        "/itinerary-items/{item_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[dict[str, object]],
    )
    def delete_itinerary_item(
        item_id: ItemIdentifier,
        service: BackendService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.delete_itinerary_item(item_id))

    app.include_router(router)
    return app


app = create_app()
