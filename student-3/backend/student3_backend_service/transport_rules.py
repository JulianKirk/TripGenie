from __future__ import annotations

from .errors import VALIDATION_ERROR_MESSAGE, ApiError, validation_error
from .models import (
    ACTIVE_PLAN_STATUSES,
    MAX_COMPARE_SELECTION,
    AvailabilityStatus,
    PlannedTransport,
    PricingBasis,
    TransportOptionRecord,
    TransportType,
    TripTransportPin,
)

# A comparison table stops being readable well before this, and an unbounded
# selection would let one request pull the whole catalogue.
COMPARE_LIMIT = MAX_COMPARE_SELECTION


def ensure_ordered_price_range(
    min_price: float | None,
    max_price: float | None,
) -> None:
    if min_price is None or max_price is None:
        return

    if min_price > max_price:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [{"field": "min_price", "issue": "must not be greater than max_price"}],
        )


def ensure_ordered_departure_window(
    departure_from: str | None,
    departure_to: str | None,
) -> None:
    if departure_from is None or departure_to is None:
        return

    if departure_from > departure_to:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [
                {
                    "field": "departure_from",
                    "issue": "must not be later than departure_to",
                },
            ],
        )


def ensure_compare_selection_within_limit(transport_ids: list[str]) -> None:
    if len(transport_ids) > COMPARE_LIMIT:
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [
                {
                    "field": "ids",
                    "issue": f"must not select more than {COMPARE_LIMIT} options",
                },
            ],
        )


def ensure_compare_selection_is_distinct(transport_ids: list[str]) -> None:
    if len(set(transport_ids)) != len(transport_ids):
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [{"field": "ids", "issue": "must not repeat a transport option"}],
        )


def ensure_route_is_a_journey(
    transport_type: TransportType,
    origin: str,
    destination: str,
) -> None:
    """Reject a leg that starts and ends in the same place.

    Car hire is exempt: collecting and returning a vehicle at one depot is the
    normal case, and the delivered seed data relies on it.
    """
    if transport_type is TransportType.CAR_RENTAL:
        return

    if origin.strip().casefold() == destination.strip().casefold():
        raise validation_error(
            VALIDATION_ERROR_MESSAGE,
            [
                {
                    "field": "destination",
                    "issue": "must differ from origin for this transport type",
                },
            ],
        )


# An operator-declared status a traveller cannot act on. Kept separate from
# the seat count, which is a different fact.
UNSELECTABLE_STATUSES = frozenset(
    {AvailabilityStatus.SOLD_OUT, AvailabilityStatus.CANCELLED},
)


def is_active_selection(pin: TripTransportPin) -> bool:
    """Whether a selection still counts toward a trip's cost and seats."""
    return pin.plan_status in ACTIVE_PLAN_STATUSES


def selection_cost(option: TransportOptionRecord, traveller_count: int) -> float:
    """What one selection contributes, in the option's own pricing terms.

    Computed in whole cents so a long itinerary cannot accumulate floating
    point drift, which matters because Student 5's budget feature consumes the
    total. Whole-vehicle hire is not multiplied by the party size -- doing so
    would overstate a car rental by the number of travellers.
    """
    if option.pricing_basis is PricingBasis.PER_VEHICLE:
        return round(option.price * 100) / 100
    return round(option.price * 100) * traveller_count / 100


def active_plan_cost_total(planned: list[PlannedTransport]) -> float:
    """Estimated cost of the selections that still count toward a trip."""
    cents = sum(
        round(item.estimated_cost * 100)
        for item in planned
        if is_active_selection(item.entry)
    )
    return cents / 100


def count_active_plan_entries(planned: list[PlannedTransport]) -> int:
    return sum(1 for item in planned if is_active_selection(item.entry))


def sort_options_for_comparison(
    options: list[TransportOptionRecord],
) -> list[TransportOptionRecord]:
    return sorted(
        options,
        key=lambda option: (option.departure_time, option.price, option.id),
    )



def missing_trip_error(trip_id: str) -> ApiError:
    return validation_error(
        VALIDATION_ERROR_MESSAGE,
        [{"field": "trip_id", "issue": f"trip '{trip_id}' does not exist"}],
    )


def ensure_option_is_selectable(option: TransportOptionRecord) -> None:
    """Refuse to attach an option a traveller could not actually take.

    Availability is declared by the operator and is not derived from the seat
    count, so this is a separate check from capacity below.
    """
    if option.availability_status in UNSELECTABLE_STATUSES:
        raise ApiError(
            status_code=409,
            code="CONFLICT",
            message="That transport option cannot be added to a trip.",
            details=[
                {
                    "field": "transport_id",
                    "issue": (
                        f"option is {option.availability_status.value}"
                    ),
                },
            ],
        )


def ensure_seats_available(
    option: TransportOptionRecord,
    already_taken: int,
    requested: int,
) -> None:
    """Refuse a selection that would oversubscribe the service.

    Checked when a selection is written rather than derived on every read: the
    figures live in the itinerary service, so one lookup on a write is cheap
    where a lookup per option per page is not.

    This guards demo-data integrity. It is not a live inventory guarantee and
    must never be presented to a traveller as one.
    """
    remaining = option.capacity - already_taken
    if requested > remaining:
        raise ApiError(
            status_code=409,
            code="CONFLICT",
            message="That transport option does not have room for the party.",
            details=[
                {
                    "field": "traveller_count",
                    "issue": (
                        f"only {max(remaining, 0)} of {option.capacity} "
                        f"seat(s) remain"
                    ),
                },
            ],
        )
