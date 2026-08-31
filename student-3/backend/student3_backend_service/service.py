from __future__ import annotations

from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError
from .models import (
    AvailabilityStatus,
    BookingStatus,
    DeleteResponse,
    DependencyStatus,
    HealthDependencies,
    HealthResponse,
    PlannedTransport,
    TransportOptionCreate,
    TransportOptionRecord,
    TransportOptionUpdate,
    TransportPlanEntryCreate,
    TransportPlanEntryRecord,
    TransportPlanEntryUpdate,
    TransportType,
    TripDirectory,
    TripTransportSummary,
)
from .transport_rules import (
    active_plan_cost_total,
    count_active_plan_entries,
    ensure_compare_selection_is_distinct,
    ensure_compare_selection_within_limit,
    ensure_ordered_departure_window,
    ensure_ordered_price_range,
    ensure_route_is_a_journey,
    missing_trip_error,
    sort_options_for_comparison,
)
from .trips_client import TripsApiClient

_DB_OK_DETAIL = "Database API responded successfully."


class BackendService:
    """Business rules for the Student 3 public API.

    Every data access is delegated to the database service over HTTP. This layer
    owns cross-record rules, the composed trip view, and dependency reporting.
    """

    def __init__(
        self,
        settings: Settings,
        client: DatabaseApiClient,
        trips_client: TripsApiClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._trips_client = trips_client

    # ------------------------------------------------------------------ health

    def health(self) -> HealthResponse:
        database = self._probe_database()
        return HealthResponse(
            status="ok" if database.status == "ok" else "degraded",
            service=self._settings.service_name,
            dependencies=HealthDependencies(database=database),
        )

    def ready(self) -> tuple[int, HealthResponse]:
        database = self._probe_database()
        is_ready = database.status == "ok"
        return (
            200 if is_ready else 503,
            HealthResponse(
                status="ok" if is_ready else "unavailable",
                service=self._settings.service_name,
                dependencies=HealthDependencies(database=database),
            ),
        )

    def _probe_database(self) -> DependencyStatus:
        try:
            payload = self._client.health()
        except ApiError as exc:
            return DependencyStatus(
                status="unavailable",
                service="student-3-database",
                detail=exc.message,
                code=exc.code,
            )

        return DependencyStatus(
            status="ok" if payload.status == "ok" else "degraded",
            service=payload.service,
            detail=_DB_OK_DETAIL,
            code=None,
        )

    # --------------------------------------------------------------- options

    def list_transport_options(
        self,
        *,
        transport_type: TransportType | None = None,
        provider: str | None = None,
        origin: str | None = None,
        destination: str | None = None,
        availability_status: AvailabilityStatus | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        departure_from: str | None = None,
        departure_to: str | None = None,
    ) -> list[TransportOptionRecord]:
        ensure_ordered_price_range(min_price, max_price)
        ensure_ordered_departure_window(departure_from, departure_to)
        return self._client.list_transport_options(
            transport_type=transport_type,
            provider=provider,
            origin=origin,
            destination=destination,
            availability_status=availability_status,
            min_price=min_price,
            max_price=max_price,
            departure_from=departure_from,
            departure_to=departure_to,
        )

    def create_transport_option(
        self,
        payload: TransportOptionCreate,
    ) -> TransportOptionRecord:
        ensure_route_is_a_journey(payload.type, payload.origin, payload.destination)
        return self._client.create_transport_option(payload)

    def get_transport_option(self, transport_id: str) -> TransportOptionRecord:
        return self._client.get_transport_option(transport_id)

    def update_transport_option(
        self,
        transport_id: str,
        payload: TransportOptionUpdate,
    ) -> TransportOptionRecord:
        """Validate the effective record, then forward the partial update.

        A PATCH can change any one of type, origin, or destination, so the route
        rule has to be checked against the merged values rather than the payload
        alone. The database service remains the final validation guard.
        """
        updates = payload.model_dump(exclude_unset=True)
        if {"type", "origin", "destination"} & updates.keys():
            existing = self._client.get_transport_option(transport_id)
            merged = existing.model_dump() | updates
            ensure_route_is_a_journey(
                TransportType(merged["type"]),
                str(merged["origin"]),
                str(merged["destination"]),
            )

        return self._client.update_transport_option(transport_id, payload)

    def delete_transport_option(self, transport_id: str) -> DeleteResponse:
        return self._client.delete_transport_option(transport_id)

    def compare_transport_options(
        self,
        transport_ids: list[str],
    ) -> list[TransportOptionRecord]:
        """Fetch a small explicit selection for side-by-side comparison.

        Unknown identifiers surface as 404 from the database service rather than
        being silently dropped, so the caller cannot be misled into comparing a
        shorter list than it asked for.
        """
        ensure_compare_selection_within_limit(transport_ids)
        ensure_compare_selection_is_distinct(transport_ids)
        options = [
            self._client.get_transport_option(transport_id)
            for transport_id in transport_ids
        ]
        return sort_options_for_comparison(options)

    def list_entries_for_option(
        self,
        transport_id: str,
        *,
        booking_status: BookingStatus | None = None,
    ) -> list[TransportPlanEntryRecord]:
        return self._client.list_entries_for_option(
            transport_id,
            booking_status=booking_status,
        )

    # ----------------------------------------------------------- plan entries

    def list_plan_entries(
        self,
        *,
        trip_id: str | None = None,
        transport_id: str | None = None,
        booking_status: BookingStatus | None = None,
    ) -> list[TransportPlanEntryRecord]:
        return self._client.list_plan_entries(
            trip_id=trip_id,
            transport_id=transport_id,
            booking_status=booking_status,
        )

    def create_plan_entry(
        self,
        payload: TransportPlanEntryCreate,
    ) -> TransportPlanEntryRecord:
        self._ensure_trip_is_known(payload.trip_id)
        return self._client.create_plan_entry(payload)

    def get_plan_entry(self, booking_id: str) -> TransportPlanEntryRecord:
        return self._client.get_plan_entry(booking_id)

    def update_plan_entry(
        self,
        booking_id: str,
        payload: TransportPlanEntryUpdate,
    ) -> TransportPlanEntryRecord:
        if payload.trip_id is not None:
            self._ensure_trip_is_known(payload.trip_id)

        return self._client.update_plan_entry(booking_id, payload)

    def trip_directory(self) -> TripDirectory:
        """Trips offered for selection, read through from Student 1.

        Read-only and best effort. Student 3 does not own trips; this exists so
        the UI can show trip names rather than requiring a typed identifier.
        """
        if self._trips_client is None:
            return TripDirectory(available=False, trips=[])

        trips = self._trips_client.list_trips()
        if trips is None:
            return TripDirectory(available=False, trips=[])

        return TripDirectory(available=True, trips=trips)

    def _ensure_trip_is_known(self, trip_id: str) -> None:
        """Reject a plan entry for a trip Student 1 says does not exist.

        Opt-in, and deliberately forgiving: only a definitive "no" blocks the
        write. An unreachable trips service leaves transport planning working.
        """
        if not self._settings.verify_trip_exists or self._trips_client is None:
            return

        if self._trips_client.trip_exists(trip_id) is False:
            raise missing_trip_error(trip_id)

    def delete_plan_entry(self, booking_id: str) -> DeleteResponse:
        return self._client.delete_plan_entry(booking_id)

    # ------------------------------------------------------- composed views

    def trip_transport(self, trip_id: str) -> TripTransportSummary:
        """Everything planned for one trip, joined to its transport options.

        The database service has no equivalent route: it would need to join
        across two tables on behalf of a caller, and the trip identifier belongs
        to Student 1. Composing it here keeps that knowledge in the backend.
        """
        entries = self._client.list_plan_entries(trip_id=trip_id)
        options: dict[str, TransportOptionRecord] = {}
        planned: list[PlannedTransport] = []

        for entry in entries:
            option = options.get(entry.transport_id)
            if option is None:
                option = self._client.get_transport_option(entry.transport_id)
                options[entry.transport_id] = option

            planned.append(PlannedTransport(entry=entry, option=option))

        planned.sort(key=lambda item: (item.option.departure_time, item.entry.id))

        return TripTransportSummary(
            trip_id=trip_id,
            entry_count=len(entries),
            active_entry_count=count_active_plan_entries(entries),
            estimated_cost_total=active_plan_cost_total(entries),
            planned=planned,
        )
