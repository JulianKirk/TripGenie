from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import ApiError, bad_request, validation_error
from .models import (
    AvailabilityStatus,
    BookingIdentifier,
    BookingStatus,
    DataEnvelope,
    DeleteResponse,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    HealthResponse,
    TransportBookingCreate,
    TransportBookingRecord,
    TransportBookingUpdate,
    TransportIdentifier,
    TransportOptionCreate,
    TransportOptionRecord,
    TransportOptionUpdate,
    TransportType,
)
from .repository import DatabaseService

VALIDATION_ERROR_MESSAGE = "One or more fields failed validation."
TRANSPORT_TYPE_VALUES = ", ".join(item.value for item in TransportType)
AVAILABILITY_STATUS_VALUES = ", ".join(item.value for item in AvailabilityStatus)
BOOKING_STATUS_VALUES = ", ".join(item.value for item in BookingStatus)
ISO_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
TRIP_ID_PATTERN = re.compile(r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
TRANSPORT_ID_PATTERN = re.compile(r"^transport_[A-Za-z0-9][A-Za-z0-9_-]{2,53}$")
MAX_QUERY_PRICE = 1_000_000.0


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


def get_service(request: Request) -> DatabaseService:
    return request.app.state.database_service


def envelope(payload: object) -> dict[str, object]:
    return {"data": payload}


def _query_validation_details(field: str, issue: str) -> list[dict[str, str]]:
    return [{"field": field, "issue": issue}]


def _raise_query_error(field: str, issue: str) -> None:
    raise validation_error(
        VALIDATION_ERROR_MESSAGE,
        _query_validation_details(field, issue),
    )


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
        _raise_query_error(field, "must not be blank")

    if max_length is not None and len(cleaned) > max_length:
        _raise_query_error(field, f"must be at most {max_length} characters")

    return cleaned


def _parse_enum_filter(value: str | None, *, field: str, enum_type, allowed: str):
    cleaned = _normalise_optional_query_text(value, field=field)
    if cleaned is None:
        return None

    try:
        return enum_type(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(field, f"must be one of: {allowed}"),
        ) from exc


def _parse_price_filter(value: str | None, *, field: str) -> float | None:
    cleaned = _normalise_optional_query_text(value, field=field)
    if cleaned is None:
        return None

    try:
        price = float(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(field, "must be a number"),
        ) from exc

    if price != price or price in {float("inf"), float("-inf")}:
        _raise_query_error(field, "must be a number")

    if price < 0 or price > MAX_QUERY_PRICE:
        _raise_query_error(field, f"must be between 0 and {MAX_QUERY_PRICE:.0f}")

    return price


def _parse_datetime_filter(value: str | None, *, field: str) -> str | None:
    cleaned = _normalise_optional_query_text(value, field=field)
    if cleaned is None:
        return None

    try:
        if ISO_DATETIME_PATTERN.fullmatch(cleaned) is None:
            raise ValueError
        datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            _query_validation_details(
                field,
                "must be a valid ISO timestamp in YYYY-MM-DDTHH:MM format",
            ),
        ) from exc

    return cleaned


def _parse_identifier_filter(
    value: str | None,
    *,
    field: str,
    pattern: re.Pattern[str],
) -> str | None:
    cleaned = _normalise_optional_query_text(value, field=field, max_length=64)
    if cleaned is None:
        return None

    if pattern.fullmatch(cleaned) is None:
        _raise_query_error(field, f"must match {pattern.pattern}")

    return cleaned


def parse_transport_type_filter(
    value: Annotated[str | None, Query(alias="type")] = None,
) -> TransportType | None:
    return _parse_enum_filter(
        value,
        field="type",
        enum_type=TransportType,
        allowed=TRANSPORT_TYPE_VALUES,
    )


def parse_provider_filter(
    value: Annotated[str | None, Query(alias="provider")] = None,
) -> str | None:
    return _normalise_optional_query_text(value, field="provider", max_length=255)


def parse_origin_filter(
    value: Annotated[str | None, Query(alias="origin")] = None,
) -> str | None:
    return _normalise_optional_query_text(value, field="origin", max_length=255)


def parse_destination_filter(
    value: Annotated[str | None, Query(alias="destination")] = None,
) -> str | None:
    return _normalise_optional_query_text(value, field="destination", max_length=255)


def parse_availability_filter(
    value: Annotated[str | None, Query(alias="availability_status")] = None,
) -> AvailabilityStatus | None:
    return _parse_enum_filter(
        value,
        field="availability_status",
        enum_type=AvailabilityStatus,
        allowed=AVAILABILITY_STATUS_VALUES,
    )


def parse_min_price_filter(
    value: Annotated[str | None, Query(alias="min_price")] = None,
) -> float | None:
    return _parse_price_filter(value, field="min_price")


def parse_max_price_filter(
    value: Annotated[str | None, Query(alias="max_price")] = None,
) -> float | None:
    return _parse_price_filter(value, field="max_price")


def parse_departure_from_filter(
    value: Annotated[str | None, Query(alias="departure_from")] = None,
) -> str | None:
    return _parse_datetime_filter(value, field="departure_from")


def parse_departure_to_filter(
    value: Annotated[str | None, Query(alias="departure_to")] = None,
) -> str | None:
    return _parse_datetime_filter(value, field="departure_to")


def parse_trip_id_filter(
    value: Annotated[str | None, Query(alias="trip_id")] = None,
) -> str | None:
    return _parse_identifier_filter(value, field="trip_id", pattern=TRIP_ID_PATTERN)


def parse_transport_id_filter(
    value: Annotated[str | None, Query(alias="transport_id")] = None,
) -> str | None:
    return _parse_identifier_filter(
        value,
        field="transport_id",
        pattern=TRANSPORT_ID_PATTERN,
    )


def parse_booking_status_filter(
    value: Annotated[str | None, Query(alias="booking_status")] = None,
) -> BookingStatus | None:
    return _parse_enum_filter(
        value,
        field="booking_status",
        enum_type=BookingStatus,
        allowed=BOOKING_STATUS_VALUES,
    )


def _ensure_ordered_range(
    lower: object | None,
    upper: object | None,
    *,
    lower_field: str,
    upper_field: str,
) -> None:
    if lower is None or upper is None:
        return

    if lower > upper:
        _raise_query_error(lower_field, f"must not be greater than {upper_field}")


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = DatabaseService(app_settings)
        service.initialize()
        app.state.database_service = service
        yield

    app = FastAPI(
        title="TripGenie Student 3 Transport Database API",
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
    option_query_params = Depends(
        allow_query_params(
            "type",
            "provider",
            "origin",
            "destination",
            "availability_status",
            "min_price",
            "max_price",
            "departure_from",
            "departure_to",
        ),
    )
    booking_query_params = Depends(
        allow_query_params("trip_id", "transport_id", "booking_status"),
    )
    option_booking_query_params = Depends(allow_query_params("booking_status"))

    @router.get(
        "/health",
        dependencies=[no_query_params],
        response_model=HealthResponse,
    )
    def health(service: DatabaseService = Depends(get_service)) -> dict[str, str]:
        return service.health()

    @router.get(
        "/transport-options",
        dependencies=[option_query_params],
        response_model=DataEnvelope[list[TransportOptionRecord]],
    )
    def list_transport_options(
        transport_type: Annotated[
            TransportType | None,
            Depends(parse_transport_type_filter),
        ],
        provider: Annotated[str | None, Depends(parse_provider_filter)],
        origin: Annotated[str | None, Depends(parse_origin_filter)],
        destination: Annotated[str | None, Depends(parse_destination_filter)],
        availability_status: Annotated[
            AvailabilityStatus | None,
            Depends(parse_availability_filter),
        ],
        min_price: Annotated[float | None, Depends(parse_min_price_filter)],
        max_price: Annotated[float | None, Depends(parse_max_price_filter)],
        departure_from: Annotated[str | None, Depends(parse_departure_from_filter)],
        departure_to: Annotated[str | None, Depends(parse_departure_to_filter)],
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        _ensure_ordered_range(
            min_price,
            max_price,
            lower_field="min_price",
            upper_field="max_price",
        )
        _ensure_ordered_range(
            departure_from,
            departure_to,
            lower_field="departure_from",
            upper_field="departure_to",
        )
        return envelope(
            service.list_transport_options(
                transport_type=transport_type,
                provider=provider,
                origin=origin,
                destination=destination,
                availability_status=availability_status,
                min_price=min_price,
                max_price=max_price,
                departure_from=departure_from,
                departure_to=departure_to,
            ),
        )

    @router.post(
        "/transport-options",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TransportOptionRecord],
        status_code=status.HTTP_201_CREATED,
    )
    def create_transport_option(
        payload: TransportOptionCreate,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.create_transport_option(payload))

    @router.get(
        "/transport-options/{transport_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TransportOptionRecord],
    )
    def get_transport_option(
        transport_id: TransportIdentifier,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.get_transport_option(transport_id))

    @router.patch(
        "/transport-options/{transport_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TransportOptionRecord],
    )
    def update_transport_option(
        transport_id: TransportIdentifier,
        payload: TransportOptionUpdate,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.update_transport_option(transport_id, payload))

    @router.delete(
        "/transport-options/{transport_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[DeleteResponse],
    )
    def delete_transport_option(
        transport_id: TransportIdentifier,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.delete_transport_option(transport_id))

    @router.get(
        "/transport-options/{transport_id}/bookings",
        dependencies=[option_booking_query_params],
        response_model=DataEnvelope[list[TransportBookingRecord]],
    )
    def list_bookings_for_option(
        transport_id: TransportIdentifier,
        booking_status: Annotated[
            BookingStatus | None,
            Depends(parse_booking_status_filter),
        ],
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(
            service.list_transport_bookings(
                transport_id=transport_id,
                booking_status=booking_status,
            ),
        )

    @router.get(
        "/transport-bookings",
        dependencies=[booking_query_params],
        response_model=DataEnvelope[list[TransportBookingRecord]],
    )
    def list_transport_bookings(
        trip_id: Annotated[str | None, Depends(parse_trip_id_filter)],
        transport_id: Annotated[str | None, Depends(parse_transport_id_filter)],
        booking_status: Annotated[
            BookingStatus | None,
            Depends(parse_booking_status_filter),
        ],
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(
            service.list_transport_bookings(
                trip_id=trip_id,
                transport_id=transport_id,
                booking_status=booking_status,
            ),
        )

    @router.post(
        "/transport-bookings",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TransportBookingRecord],
        status_code=status.HTTP_201_CREATED,
    )
    def create_transport_booking(
        payload: TransportBookingCreate,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.create_transport_booking(payload))

    @router.get(
        "/transport-bookings/{booking_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TransportBookingRecord],
    )
    def get_transport_booking(
        booking_id: BookingIdentifier,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.get_transport_booking(booking_id))

    @router.patch(
        "/transport-bookings/{booking_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[TransportBookingRecord],
    )
    def update_transport_booking(
        booking_id: BookingIdentifier,
        payload: TransportBookingUpdate,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.update_transport_booking(booking_id, payload))

    @router.delete(
        "/transport-bookings/{booking_id}",
        dependencies=[no_query_params],
        response_model=DataEnvelope[DeleteResponse],
    )
    def delete_transport_booking(
        booking_id: BookingIdentifier,
        service: DatabaseService = Depends(get_service),
    ) -> dict[str, object]:
        return envelope(service.delete_transport_booking(booking_id))

    app.include_router(router)
    return app


app = create_app()
