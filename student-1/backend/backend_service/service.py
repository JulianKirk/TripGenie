from __future__ import annotations

from datetime import date, timedelta

from .ai_suggestions import AiSuggestionRequest, AiSuggestionService
from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError, validation_error
from .models import (
    DependencyStatus,
    HealthDependencies,
    HealthResponse,
    ItineraryCategory,
    ItineraryItemCreate,
    ItineraryItemRecord,
    ItineraryItemUpdate,
    TripCreate,
    TripDay,
    TripDaySelection,
    TripDetail,
    TripRecord,
    TripStatus,
    TripUpdate,
)
from .trip_rules import ensure_trip_detail_supported, validate_trip_window

VALIDATION_ERROR_MESSAGE = "One or more fields failed validation."


class BackendService:
    def __init__(
        self,
        client: DatabaseApiClient,
        ai_suggestions: AiSuggestionService,
        settings: Settings,
    ) -> None:
        self._client = client
        self._ai_suggestions = ai_suggestions
        self._settings = settings

    def list_trips(
        self,
        *,
        status: TripStatus | None = None,
        destination: str | None = None,
    ) -> list[dict[str, object]]:
        trips = self._client.list_trips(status=status, destination=destination)
        return [trip.model_dump(mode="json") for trip in trips]

    def create_trip(self, payload: TripCreate) -> dict[str, object]:
        validate_trip_window(
            payload.start_date,
            payload.end_date,
            message=VALIDATION_ERROR_MESSAGE,
        )
        created_trip = self._client.create_trip(payload)
        return self._build_trip_detail(created_trip, [])

    def get_trip(self, trip_id: str) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        ensure_trip_detail_supported(trip)
        items = self._client.list_itinerary_items(trip_id)
        return self._build_trip_detail(trip, items)

    def get_trip_day(self, trip_id: str, trip_day: str) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        self._ensure_date_within_trip(trip_day, trip)
        items = self._client.list_itinerary_items(trip_id, date=trip_day)
        return TripDaySelection(
            trip_id=trip.id,
            date=trip_day,
            items=items,
        ).model_dump(mode="json")

    async def create_ai_suggestions(
        self,
        trip_id: str,
        payload: AiSuggestionRequest,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        ensure_trip_detail_supported(trip)
        self._ensure_date_within_trip(payload.requested_date, trip)
        items = self._client.list_itinerary_items(trip_id)
        response = await self._ai_suggestions.generate(
            trip_id=trip_id,
            trip=trip,
            existing_items=items,
            request=payload,
            correlation_id=correlation_id,
        )
        return response.model_dump(mode="json")

    def update_trip(self, trip_id: str, payload: TripUpdate) -> dict[str, object]:
        updates = payload.model_dump(exclude_unset=True, mode="json")
        if not updates:
            raise validation_error(
                VALIDATION_ERROR_MESSAGE,
                [{"field": "body", "issue": "at least one field must be provided"}],
            )

        existing_trip = self._client.get_trip(trip_id)
        merged_trip = existing_trip.model_dump(mode="json") | updates
        TripRecord.model_validate(merged_trip)
        validate_trip_window(
            str(merged_trip["start_date"]),
            str(merged_trip["end_date"]),
            message=VALIDATION_ERROR_MESSAGE,
        )
        existing_items = self._client.list_itinerary_items(trip_id)
        self._ensure_trip_window_covers_items(merged_trip, existing_items)

        # The current internal API does not expose versioned writes, so PATCH remains
        # read-merge-write across services. Re-reading after the write reduces stale
        # responses while the database API remains the final validation guard.
        updated_trip = self._client.update_trip(trip_id, payload)
        ensure_trip_detail_supported(updated_trip)
        refreshed_items = self._client.list_itinerary_items(trip_id)
        return self._build_trip_detail(updated_trip, refreshed_items)

    def delete_trip(self, trip_id: str) -> dict[str, object]:
        deleted = self._client.delete_trip(trip_id)
        return deleted.model_dump(mode="json")

    def list_itinerary_items(
        self,
        trip_id: str,
        *,
        date: str | None = None,
        category: ItineraryCategory | None = None,
    ) -> list[dict[str, object]]:
        items = self._client.list_itinerary_items(
            trip_id,
            date=date,
            category=category,
        )
        return [item.model_dump(mode="json") for item in items]

    def create_itinerary_item(
        self,
        trip_id: str,
        payload: ItineraryItemCreate,
    ) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        self._validate_item_record(
            {
                **payload.model_dump(mode="json"),
                "id": payload.id or "item_validation_preview",
                "trip_id": trip_id,
            },
            trip,
        )
        created_item = self._client.create_itinerary_item(trip_id, payload)
        return created_item.model_dump(mode="json")

    def get_itinerary_item(self, item_id: str) -> dict[str, object]:
        item = self._client.get_itinerary_item(item_id)
        return item.model_dump(mode="json")

    def update_itinerary_item(
        self,
        item_id: str,
        payload: ItineraryItemUpdate,
    ) -> dict[str, object]:
        updates = payload.model_dump(exclude_unset=True, mode="json")
        if not updates:
            raise validation_error(
                VALIDATION_ERROR_MESSAGE,
                [{"field": "body", "issue": "at least one field must be provided"}],
            )

        existing_item = self._client.get_itinerary_item(item_id)
        trip = self._client.get_trip(existing_item.trip_id)
        merged_item = existing_item.model_dump(mode="json") | updates
        self._validate_item_record(merged_item, trip)
        updated_item = self._client.update_itinerary_item(item_id, payload)
        return updated_item.model_dump(mode="json")

    def delete_itinerary_item(self, item_id: str) -> dict[str, object]:
        deleted = self._client.delete_itinerary_item(item_id)
        return deleted.model_dump(mode="json")

    async def health(self) -> HealthResponse:
        database = self._probe_database()
        ai_mode = await self._ai_mode_status()
        overall_status = (
            "ok"
            if database.status == "ok"
            and ai_mode.status in {"ok", "not_configured"}
            else "degraded"
        )
        return HealthResponse(
            status=overall_status,
            service=self._settings.service_name,
            dependencies=HealthDependencies(database=database, ai_mode=ai_mode),
        )

    def ready(self) -> tuple[int, HealthResponse]:
        database = self._probe_database()
        ai_mode = self._ai_suggestions.readiness_dependency_status()
        is_ready = database.status == "ok"
        return (
            200 if is_ready else 503,
            HealthResponse(
                status="ok" if is_ready else "unavailable",
                service=self._settings.service_name,
                dependencies=HealthDependencies(database=database, ai_mode=ai_mode),
            ),
        )

    @staticmethod
    def _ensure_date_within_trip(trip_day: str, trip: TripRecord) -> None:
        if trip.start_date <= trip_day <= trip.end_date:
            return

        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [
                {
                    "field": "date",
                    "issue": (
                        f"must fall between {trip.start_date} and {trip.end_date}"
                    ),
                },
            ],
        )

    @staticmethod
    def _ensure_trip_window_covers_items(
        merged_trip: dict[str, object],
        items: list[ItineraryItemRecord],
    ) -> None:
        conflicting_dates = sorted(
            {
                item.date
                for item in items
                if item.date < str(merged_trip["start_date"])
                or item.date > str(merged_trip["end_date"])
            },
        )
        if not conflicting_dates:
            return

        sample_dates = ", ".join(conflicting_dates[:3])
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [
                {
                    "field": "start_date",
                    "issue": (
                        "cannot exclude existing itinerary item dates "
                        f"({sample_dates})"
                    ),
                },
            ],
        )

    @staticmethod
    def _validate_item_record(
        record: dict[str, object],
        trip: TripRecord,
    ) -> None:
        ItineraryItemRecord.model_validate(record)
        errors: list[dict[str, str]] = []

        item_date = str(record["date"])
        if item_date < trip.start_date or item_date > trip.end_date:
            errors.append(
                {
                    "field": "date",
                    "issue": (
                        f"must fall between {trip.start_date} and {trip.end_date}"
                    ),
                },
            )

        start_time = record.get("start_time")
        end_time = record.get("end_time")
        if start_time is not None and end_time is not None and start_time >= end_time:
            errors.append(
                {
                    "field": "start_time",
                    "issue": "must be earlier than end_time when both are provided",
                },
            )

        if errors:
            raise validation_error(VALIDATION_ERROR_MESSAGE, errors)

    @staticmethod
    def _build_trip_detail(
        trip: TripRecord,
        items: list[ItineraryItemRecord],
    ) -> dict[str, object]:
        ensure_trip_detail_supported(trip)
        items_by_date: dict[str, list[ItineraryItemRecord]] = {}
        for item in items:
            items_by_date.setdefault(item.date, []).append(item)

        current_day = date.fromisoformat(trip.start_date)
        final_day = date.fromisoformat(trip.end_date)
        days: list[TripDay] = []
        while current_day <= final_day:
            iso_day = current_day.isoformat()
            days.append(TripDay(date=iso_day, items=items_by_date.get(iso_day, [])))
            current_day += timedelta(days=1)

        return TripDetail(
            **trip.model_dump(mode="json"),
            days=days,
        ).model_dump(mode="json")

    def _probe_database(self) -> DependencyStatus:
        try:
            payload = self._client.health()
        except ApiError as exc:
            return self._dependency_status_from_error(exc)

        status = payload.status.lower()
        if status == "ok":
            return DependencyStatus(
                status="ok",
                service=payload.service,
                detail="Database API responded successfully.",
            )

        return DependencyStatus(
            status="degraded",
            service=payload.service,
            detail=f"Database API reported status '{payload.status}'.",
        )

    async def _ai_mode_status(self) -> DependencyStatus:
        return await self._ai_suggestions.dependency_status()

    @staticmethod
    def _dependency_status_from_error(exc: ApiError) -> DependencyStatus:
        status_map = {
            "DEPENDENCY_TIMEOUT": "timeout",
            "DEPENDENCY_UNAVAILABLE": "unavailable",
            "BAD_GATEWAY": "invalid_response",
            "DATABASE_BUSY": "busy",
        }
        return DependencyStatus(
            status=status_map.get(exc.code, "unavailable"),
            service="student-1-database",
            detail=exc.message,
            code=exc.code,
        )
