from __future__ import annotations

from .errors import VALIDATION_ERROR_MESSAGE, ApiError, validation_error
from .models import (
    ACTIVE_PLAN_STATUSES,
    MAX_COMPARE_SELECTION,
    TransportOptionRecord,
    TransportPlanEntryRecord,
    TransportType,
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


def is_active_plan_entry(entry: TransportPlanEntryRecord) -> bool:
    return entry.booking_status in ACTIVE_PLAN_STATUSES


def active_plan_cost_total(entries: list[TransportPlanEntryRecord]) -> float:
    """Estimated cost of the entries that still count toward a trip.

    Summed in whole cents so a long itinerary cannot accumulate floating point
    drift, which matters because Student 5's budget feature consumes this.
    """
    cents = sum(
        round(entry.estimated_cost * 100)
        for entry in entries
        if is_active_plan_entry(entry)
    )
    return cents / 100


def count_active_plan_entries(entries: list[TransportPlanEntryRecord]) -> int:
    return sum(1 for entry in entries if is_active_plan_entry(entry))


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
