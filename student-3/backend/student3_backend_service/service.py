from __future__ import annotations

from uuid import uuid4

from .ai_mode_client import AiModeClient
from .ai_suggestions import build_prompt, resolve_draft, select_candidates
from .client import DatabaseApiClient
from .config import Settings
from .errors import ApiError, dependency_unavailable, validation_error
from .models import (
    AvailabilityStatus,
    DeleteResponse,
    DependencyStatus,
    HealthDependencies,
    HealthResponse,
    ItinerarySelection,
    ItinerarySelectionRequest,
    ItinerarySelectionResponse,
    PlannedTransport,
    TransportOptionCreate,
    TransportOptionRecord,
    TransportOptionUpdate,
    TransportRecommendationRequest,
    TransportRecommendationResponse,
    TransportType,
    TripDirectory,
    TripTransportPin,
    TripTransportSummary,
)
from .transport_rules import (
    active_plan_cost_total,
    count_active_plan_entries,
    ensure_compare_selection_is_distinct,
    ensure_compare_selection_within_limit,
    ensure_option_is_selectable,
    ensure_ordered_departure_window,
    ensure_ordered_price_range,
    ensure_route_is_a_journey,
    ensure_seats_available,
    is_active_selection,
    missing_trip_error,
    selection_cost,
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
        ai_client: AiModeClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._trips_client = trips_client
        self._ai_client = ai_client

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

    # ----------------------------------------------------------------- seats

    def _traveller_totals(self) -> dict[str, int] | None:
        """Travellers selected per option, or None when that cannot be read.

        None is not zero. The selections live in the itinerary service, so when
        it cannot be reached the seat count is unknown -- and an unknown count
        must not be rendered as a full or an empty service.
        """
        if self._trips_client is None:
            return None
        try:
            return self._trips_client.traveller_totals()
        except ApiError:
            return None

    def _with_seats(
        self,
        options: list[TransportOptionRecord],
        totals: dict[str, int] | None,
    ) -> list[TransportOptionRecord]:
        if totals is None:
            return options
        return [
            option.model_copy(
                update={
                    "seats_remaining": max(
                        option.capacity - totals.get(option.id, 0),
                        0,
                    ),
                },
            )
            for option in options
        ]

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
        options = self._client.list_transport_options(
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
        return self._with_seats(options, self._traveller_totals())

    def create_transport_option(
        self,
        payload: TransportOptionCreate,
    ) -> TransportOptionRecord:
        ensure_route_is_a_journey(payload.type, payload.origin, payload.destination)
        created = self._client.create_transport_option(payload)
        return self._with_seats([created], self._traveller_totals())[0]

    def get_transport_option(self, transport_id: str) -> TransportOptionRecord:
        option = self._client.get_transport_option(transport_id)
        return self._with_seats([option], self._traveller_totals())[0]

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

        updated = self._client.update_transport_option(transport_id, payload)
        return self._with_seats([updated], self._traveller_totals())[0]

    def delete_transport_option(self, transport_id: str) -> DeleteResponse:
        """Delete an option, unless a trip still holds it.

        The database service used to refuse this itself, by way of a foreign
        key to its own selections table. Those rows live in the itinerary
        service now, so nothing there can see them and the guard has to be
        re-made here -- otherwise deleting an option would leave Student 1 with
        rows pointing at something that no longer exists, and a trip page
        showing a journey it cannot name.

        Best-effort on purpose: if the itinerary service cannot be reached the
        delete proceeds. Blocking catalogue maintenance during someone else's
        outage would be the worse failure, and the alternative -- refusing every
        delete when the answer is unknown -- makes this service unusable
        whenever Student 1 is down.
        """
        if self._trips_client is not None:
            try:
                holding = self._trips_client.trips_for_transport(transport_id)
            except ApiError:
                holding = []
            if holding:
                names = ", ".join(trip.name for trip in holding[:3])
                raise ApiError(
                    status_code=409,
                    code="CONFLICT",
                    message="That transport option is still part of a trip.",
                    details=[
                        {
                            "field": "transport_id",
                            "issue": (
                                f"{len(holding)} trip(s) still hold it ({names}). "
                                "Remove it from them first."
                            ),
                        },
                    ],
                )

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

    # ----------------------------------------------------------- plan entries

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

    # ------------------------------------------------------- AI suggestions

    def recommend_transport(
        self,
        payload: TransportRecommendationRequest,
    ) -> TransportRecommendationResponse:
        """Draft advice for a traveller. Advisory only, never saved here.

        The whole flow is Plan (assemble a bounded candidate list) -> Act (one
        AI-Mode call) -> Observe (validate the reply against the schema and the
        candidates) -> Adapt (the traveller reviews and saves through the normal
        plan-entry route). Nothing on this path writes to the database.
        """
        if self._ai_client is None:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="AI recommendations are not configured for this service.",
                details=[{"field": "ai_mode", "issue": "client is not configured"}],
            )

        options = self._client.list_transport_options(
            origin=payload.origin,
            destination=payload.destination,
        )
        candidates = select_candidates(options, self._settings.ai_max_candidates)
        if not candidates:
            raise validation_error(
                "There are no bookable transport options to recommend from.",
                [
                    {
                        "field": "origin",
                        "issue": (
                            "no available option matches this route; widen it or "
                            "add transport options first"
                        ),
                    },
                ],
            )

        trip_plan = None
        if payload.trip_id is not None:
            self._ensure_trip_is_known(payload.trip_id)
            trip_plan = self.trip_transport(payload.trip_id)

        prompt = build_prompt(self._settings, payload, candidates, trip_plan)
        correlation_id = f"student3-transport-{uuid4().hex[:16]}"
        generated = self._ai_client.generate_draft(
            prompt=prompt,
            correlation_id=correlation_id,
            metadata={
                "service": self._settings.service_name,
                "feature": "transport-recommendations",
                "candidates": str(len(candidates)),
            },
        )

        return resolve_draft(
            generated.draft,
            candidates,
            run_id=generated.run_id,
            model=generated.model,
            provider=generated.provider,
        )

    def _ensure_trip_is_known(self, trip_id: str) -> None:
        """Reject a plan entry for a trip Student 1 says does not exist.

        Opt-in, and deliberately forgiving: only a definitive "no" blocks the
        write. An unreachable trips service leaves transport planning working.
        """
        if not self._settings.verify_trip_exists or self._trips_client is None:
            return

        if self._trips_client.trip_exists(trip_id) is False:
            raise missing_trip_error(trip_id)

    # ------------------------------------------------------- composed views

    # ------------------------------------------------------------ selections

    def _itinerary(self) -> TripsApiClient:
        """The itinerary service, or a clear refusal if it was not configured."""
        if self._trips_client is None:
            raise dependency_unavailable(
                "Transport selections need the itinerary service.",
                [{"field": "itinerary", "issue": "client not configured"}],
            )
        return self._trips_client

    def _selections_for(self, transport_id: str) -> dict[str, TripTransportPin]:
        """Every trip holding this option, keyed by trip id."""
        itinerary = self._itinerary()
        found: dict[str, TripTransportPin] = {}
        for trip in itinerary.trips_for_transport(transport_id):
            for pin in itinerary.list_trip_transport(trip.id):
                if pin.transport_id == transport_id:
                    found[trip.id] = pin
        return found

    def _compose(self, pins: list[TripTransportPin]) -> list[PlannedTransport]:
        """Join selections to the options they name, and price each one."""
        options: dict[str, TransportOptionRecord] = {}
        planned: list[PlannedTransport] = []

        for pin in pins:
            option = options.get(pin.transport_id)
            if option is None:
                option = self._client.get_transport_option(pin.transport_id)
                options[pin.transport_id] = option

            planned.append(
                PlannedTransport(
                    entry=pin,
                    option=option,
                    estimated_cost=selection_cost(option, pin.traveller_count),
                ),
            )

        # Departure order: the only order a journey reads in.
        planned.sort(
            key=lambda item: (item.option.departure_time, item.entry.transport_id),
        )
        return planned

    def trip_transport(self, trip_id: str) -> TripTransportSummary:
        """Everything selected for one trip, joined to its transport options.

        The selections belong to the itinerary service; the options and their
        prices belong here, and only this side knows whether a price is per
        traveller or per vehicle. So the join happens here, and the shape of
        this route is unchanged from when the selections were stored locally:
        Student 5 reads `estimated_cost_total` and `currency` from it and must
        not have to care that they moved.
        """
        pins = self._itinerary().list_trip_transport(trip_id)
        planned = self._compose(pins)

        return TripTransportSummary(
            trip_id=trip_id,
            currency=self._settings.currency,
            entry_count=len(planned),
            active_entry_count=count_active_plan_entries(planned),
            estimated_cost_total=active_plan_cost_total(planned),
            planned=planned,
        )

    def itinerary_selections(self, transport_id: str) -> ItinerarySelectionResponse:
        """Every trip, marked with whether it already holds this option.

        A tick-list rather than a form: a traveller recognises their own trips,
        and should not have to recall an identifier to attach transport to one.
        """
        option = self._client.get_transport_option(transport_id)
        itinerary = self._itinerary()

        trips = itinerary.list_trips()
        if trips is None:
            raise dependency_unavailable(
                "The itinerary service is unavailable.",
                [{"field": "itinerary", "issue": "trips could not be listed"}],
            )

        pins = self._selections_for(transport_id)
        selections = [
            ItinerarySelection(
                trip_id=trip.id,
                name=trip.name,
                destination=trip.destination,
                start_date=trip.start_date,
                end_date=trip.end_date,
                selected=trip.id in pins,
                traveller_count=(
                    pins[trip.id].traveller_count if trip.id in pins else None
                ),
                plan_status=pins[trip.id].plan_status if trip.id in pins else None,
                estimated_cost=(
                    selection_cost(option, pins[trip.id].traveller_count)
                    if trip.id in pins
                    else None
                ),
            )
            for trip in trips
        ]

        totals = self._traveller_totals()
        return ItinerarySelectionResponse(
            transport_id=transport_id,
            currency=self._settings.currency,
            seats_remaining=(
                max(option.capacity - totals.get(transport_id, 0), 0)
                if totals is not None
                else None
            ),
            itineraries=selections,
        )

    def add_to_itinerary(
        self,
        transport_id: str,
        trip_id: str,
        payload: ItinerarySelectionRequest,
    ) -> ItinerarySelectionResponse:
        """Attach transport to a trip, refusing to oversubscribe the service."""
        option = self._client.get_transport_option(transport_id)
        ensure_option_is_selectable(option)

        # Capacity is checked here, at the moment of writing, rather than being
        # derived on every read: one lookup on a write is cheap, and a fan-out
        # on every list page is not.
        existing = self._selections_for(transport_id)
        taken = sum(
            pin.traveller_count
            for other_trip, pin in existing.items()
            if other_trip != trip_id and is_active_selection(pin)
        )
        ensure_seats_available(option, taken, payload.traveller_count)

        self._itinerary().add_trip_transport(
            trip_id,
            transport_id,
            traveller_count=payload.traveller_count,
            plan_status=payload.plan_status.value,
            notes=payload.notes,
        )
        return self.itinerary_selections(transport_id)

    def remove_from_itinerary(
        self,
        transport_id: str,
        trip_id: str,
    ) -> ItinerarySelectionResponse:
        self._itinerary().remove_trip_transport(trip_id, transport_id)
        return self.itinerary_selections(transport_id)
