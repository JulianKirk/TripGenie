from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .accommodation_client import AccommodationClient
from .activity_client import ActivityClient, ActivityDetails
from .ai_suggestions import (
    AiSuggestionRequest,
    AiSuggestionService,
    prepare_cross_service_prompt_context,
    select_cross_service_records,
)
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
    TripAccommodationDetail,
    TripAccommodationRecord,
    TripActivityDetail,
    TripActivityRecord,
    TripCreate,
    TripDay,
    TripDaySelection,
    TripDetail,
    TripRecord,
    TripStatus,
    TripTransportCreate,
    TripTransportDetail,
    TripTransportRecord,
    TripUpdate,
)
from .transport_client import TransportClient, TransportDetails
from .trip_rules import (
    ensure_trip_detail_supported,
    validate_stay_window,
    validate_trip_window,
)

VALIDATION_ERROR_MESSAGE = "One or more fields failed validation."


class BackendService:
    def __init__(
        self,
        client: DatabaseApiClient,
        ai_suggestions: AiSuggestionService,
        settings: Settings,
        accommodations: AccommodationClient | None = None,
        activities: ActivityClient | None = None,
        transport: TransportClient | None = None,
    ) -> None:
        self._client = client
        self._ai_suggestions = ai_suggestions
        self._settings = settings
        self._accommodations = accommodations
        self._activities = activities
        self._transport = transport

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
        return self._build_trip_detail(created_trip, [], [], [], [])

    def _enrich_accommodations(
        self,
        accommodations: list[TripAccommodationRecord],
        *,
        sources: dict[str, dict[str, Any]] | None = None,
    ) -> list[TripAccommodationDetail]:
        """The pinned accommodations, with the name and price student 2 owns.

        A trip stores an id and the stay; everything the page needs to *label*
        that stay lives in the other service. When it cannot be reached the
        fields stay None and the page shows the stay without them -- losing a
        name is not a reason to lose the trip.
        """
        if not accommodations:
            return []

        found = (
            sources
            if sources is not None
            else self._accommodation_sources(accommodations)
        )
        detailed: list[TripAccommodationDetail] = []
        for record in accommodations:
            extra = found.get(record.accommodation_id, {})
            rate = extra.get("price_per_night")
            detailed.append(
                TripAccommodationDetail(
                    **record.model_dump(mode="json"),
                    name=extra.get("name"),
                    price_per_night=rate,
                    total_price=_stay_total(rate, record.date, record.check_out),
                )
            )
        return detailed

    def _accommodation_sources(
        self,
        accommodations: list[TripAccommodationRecord],
    ) -> dict[str, dict[str, Any]]:
        if self._accommodations is None:
            return {}
        return self._accommodations.details(
            [record.accommodation_id for record in accommodations]
        )

    def _enrich_activities(
        self,
        activities: list[TripActivityRecord],
        *,
        sources: dict[str, ActivityDetails] | None = None,
    ) -> list[TripActivityDetail]:
        if not activities:
            return []
        found = sources if sources is not None else self._activity_sources(activities)
        return [
            TripActivityDetail(
                **record.model_dump(mode="json"),
                name=(
                    found[record.activity_id].name
                    if record.activity_id in found
                    else None
                ),
                price=(
                    found[record.activity_id].price
                    if record.activity_id in found
                    else None
                ),
                pricing_basis=(
                    found[record.activity_id].pricing_basis
                    if record.activity_id in found
                    else None
                ),
                duration_minutes=(
                    found[record.activity_id].duration_minutes
                    if record.activity_id in found
                    else None
                ),
            )
            for record in activities
        ]

    def _activity_sources(
        self,
        activities: list[TripActivityRecord],
    ) -> dict[str, ActivityDetails]:
        if self._activities is None:
            return {}
        return self._activities.details([record.activity_id for record in activities])

    def _enrich_transport(
        self,
        transport: list[TripTransportRecord],
        *,
        sources: dict[str, TransportDetails] | None = None,
    ) -> list[TripTransportDetail]:
        """The pinned transport, labelled with what Student 3 owns.

        A trip stores the option id and the party size. The route, the times
        and the price live in the transport service, and `estimated_cost` is
        worked out there too -- per-vehicle hire must not be multiplied by the
        traveller count. When that service cannot be reached the labels stay
        None and the page shows the selection without them.
        """
        if not transport:
            return []

        found = sources if sources is not None else self._transport_sources(transport)
        detailed: list[TripTransportDetail] = []
        for record in transport:
            extra = found.get(record.transport_id)
            detailed.append(
                TripTransportDetail(
                    **record.model_dump(mode="json"),
                    origin=extra.origin if extra else None,
                    destination=extra.destination if extra else None,
                    provider=extra.provider if extra else None,
                    type=extra.type if extra else None,
                    departure_time=extra.departure_time if extra else None,
                    arrival_time=extra.arrival_time if extra else None,
                    duration_minutes=extra.duration_minutes if extra else None,
                    price=extra.price if extra else None,
                    pricing_basis=extra.pricing_basis if extra else None,
                    estimated_cost=(
                        extra.cost_for(record.traveller_count) if extra else None
                    ),
                )
            )
        # Departure order is the only order a traveller reads a journey in.
        # Rows with no detail sink to the end rather than jumbling the rest.
        detailed.sort(
            key=lambda row: (
                row.departure_time is None,
                row.departure_time or "",
                row.transport_id,
            )
        )
        return detailed

    def _transport_sources(
        self,
        transport: list[TripTransportRecord],
    ) -> dict[str, TransportDetails]:
        if self._transport is None:
            return {}
        return self._transport.details([record.transport_id for record in transport])

    def list_trip_transport(self, trip_id: str) -> list[dict[str, object]]:
        records = self._client.list_trip_transport(trip_id)
        return [
            record.model_dump(mode="json") for record in self._enrich_transport(records)
        ]

    def add_trip_transport(
        self,
        trip_id: str,
        transport_id: str,
        payload: TripTransportCreate,
    ) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        record = self._client.add_trip_transport(
            trip_id,
            transport_id,
            payload.traveller_count,
            payload.plan_status.value,
            payload.added_on or trip.start_date,
            payload.notes,
        )
        return self._enrich_transport([record])[0].model_dump(mode="json")

    def remove_trip_transport(
        self,
        trip_id: str,
        transport_id: str,
    ) -> dict[str, object]:
        deleted = self._client.remove_trip_transport(trip_id, transport_id)
        return deleted.model_dump(mode="json")

    def list_trips_for_transport(self, transport_id: str) -> list[dict[str, object]]:
        records = self._client.list_trips_for_transport(transport_id)
        return [record.model_dump(mode="json") for record in records]

    def transport_traveller_totals(self) -> list[dict[str, object]]:
        records = self._client.transport_traveller_totals()
        return [record.model_dump(mode="json") for record in records]

    def get_trip(self, trip_id: str) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        ensure_trip_detail_supported(trip)
        items = self._client.list_itinerary_items(trip_id)
        accommodations = self._client.list_trip_accommodations(trip_id)
        activities = self._client.list_trip_activities(trip_id)
        transport = self._client.list_trip_transport(trip_id)
        return self._build_trip_detail(
            trip,
            items,
            self._enrich_accommodations(accommodations),
            self._enrich_activities(activities),
            self._enrich_transport(transport),
        )

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
        accommodation_records = self._client.list_trip_accommodations(trip_id)
        activity_records = self._client.list_trip_activities(trip_id)
        transport_records = self._client.list_trip_transport(trip_id)
        selection = select_cross_service_records(
            accommodations=accommodation_records,
            activities=activity_records,
            transport=transport_records,
            request=payload,
            settings=self._settings,
        )
        accommodation_sources = self._accommodation_sources(selection.accommodations)
        activity_sources = self._activity_sources(selection.activities)
        transport_sources = self._transport_sources(selection.transport)
        cross_service_context = prepare_cross_service_prompt_context(
            selection=selection,
            enriched_accommodations=self._enrich_accommodations(
                selection.accommodations,
                sources=accommodation_sources,
            ),
            accommodation_sources=accommodation_sources,
            enriched_activities=self._enrich_activities(
                selection.activities,
                sources=activity_sources,
            ),
            enriched_transport=self._enrich_transport(
                selection.transport,
                sources=transport_sources,
            ),
        )
        response = await self._ai_suggestions.generate(
            trip_id=trip_id,
            trip=trip,
            existing_items=items,
            cross_service_context=cross_service_context,
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
        existing_activities = self._client.list_trip_activities(trip_id)
        self._ensure_trip_window_covers_activities(merged_trip, existing_activities)

        # The current internal API does not expose versioned writes, so PATCH remains
        # read-merge-write across services. Re-reading after the write reduces stale
        # responses while the database API remains the final validation guard.
        updated_trip = self._client.update_trip(trip_id, payload)
        ensure_trip_detail_supported(updated_trip)
        refreshed_items = self._client.list_itinerary_items(trip_id)
        accommodations = self._client.list_trip_accommodations(trip_id)
        activities = self._client.list_trip_activities(trip_id)
        transport = self._client.list_trip_transport(trip_id)
        return self._build_trip_detail(
            updated_trip,
            refreshed_items,
            self._enrich_accommodations(accommodations),
            self._enrich_activities(activities),
            self._enrich_transport(transport),
        )

    def delete_trip(self, trip_id: str) -> dict[str, object]:
        deleted = self._client.delete_trip(trip_id)
        return deleted.model_dump(mode="json")

    def list_trip_accommodations(self, trip_id: str) -> list[dict[str, object]]:
        records = self._client.list_trip_accommodations(trip_id)
        return [record.model_dump(mode="json") for record in records]

    def add_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
        check_in: str | None = None,
        check_out: str | None = None,
        check_in_time: str | None = None,
        check_out_time: str | None = None,
    ) -> dict[str, object]:
        """Pins an accommodation to a trip for a stay window.

        Both dates are optional. A caller that supplies neither gets what this
        did before there was anything to supply: pinned to the trip's first
        day with no departure recorded. That keeps the bodyless PUT working
        for anyone still sending one.

        The trip is fetched either way -- to default the check-in, and to have
        a window to validate against -- so the check costs no extra request.
        """
        trip = self._client.get_trip(trip_id)
        check_in = check_in or trip.start_date
        validate_stay_window(
            trip,
            check_in,
            check_out,
            check_in_time,
            check_out_time,
            message="Stay dates must fall inside the trip.",
        )
        record = self._client.add_trip_accommodation(
            trip_id,
            accommodation_id,
            check_in,
            check_out,
            check_in_time,
            check_out_time,
        )
        return record.model_dump(mode="json")

    def remove_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
    ) -> dict[str, object]:
        removed = self._client.remove_trip_accommodation(trip_id, accommodation_id)
        return removed.model_dump(mode="json")

    def list_trips_for_accommodation(
        self,
        accommodation_id: str,
    ) -> list[dict[str, object]]:
        """The reverse lookup. One query answers which boxes the accommodation
        service's picker should show ticked, instead of one call per trip."""
        trips = self._client.list_trips_for_accommodation(accommodation_id)
        return [trip.model_dump(mode="json") for trip in trips]

    def list_trip_activities(self, trip_id: str) -> list[dict[str, object]]:
        records = self._client.list_trip_activities(trip_id)
        return [record.model_dump(mode="json") for record in records]

    def add_trip_activity(
        self,
        trip_id: str,
        activity_id: str,
        activity_date: str | None = None,
        start_time: str | None = None,
    ) -> dict[str, object]:
        trip = self._client.get_trip(trip_id)
        activity_date = activity_date or trip.start_date
        self._ensure_date_within_trip(activity_date, trip)
        record = self._client.add_trip_activity(
            trip_id,
            activity_id,
            activity_date,
            start_time,
        )
        return record.model_dump(mode="json")

    def remove_trip_activity(
        self,
        trip_id: str,
        activity_id: str,
    ) -> dict[str, object]:
        removed = self._client.remove_trip_activity(trip_id, activity_id)
        return removed.model_dump(mode="json")

    def list_trips_for_activity(self, activity_id: str) -> list[dict[str, object]]:
        trips = self._client.list_trips_for_activity(activity_id)
        return [trip.model_dump(mode="json") for trip in trips]

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
            if database.status == "ok" and ai_mode.status in {"ok", "not_configured"}
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
                        f"cannot exclude existing itinerary item dates ({sample_dates})"
                    ),
                },
            ],
        )

    @staticmethod
    def _ensure_trip_window_covers_activities(
        merged_trip: dict[str, object],
        activities: list[TripActivityRecord],
    ) -> None:
        conflicting_dates = sorted(
            {
                activity.date
                for activity in activities
                if activity.date < str(merged_trip["start_date"])
                or activity.date > str(merged_trip["end_date"])
            }
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
                        f"cannot exclude existing activity dates ({sample_dates})"
                    ),
                }
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
        accommodations: list[TripAccommodationDetail],
        activities: list[TripActivityDetail],
        transport: list[TripTransportDetail],
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
            accommodations=accommodations,
            activities=activities,
            transport=transport,
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


def _stay_total(
    rate: float | None,
    check_in: str,
    check_out: str | None,
) -> float | None:
    """What the stay costs: the nightly rate times the nights between the two
    dates.

    None when there is nothing to multiply -- no rate, or no departure date yet.
    A same-day stay is nought nights and so costs nothing, which is a real
    answer rather than a missing one.
    """
    if rate is None or not check_out:
        return None
    nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    if nights < 0:
        return None
    return round(rate * nights, 2)
