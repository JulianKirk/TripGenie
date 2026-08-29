from __future__ import annotations

from datetime import date

from .errors import bad_gateway, validation_error
from .models import TripRecord

MAX_TRIP_DURATION_DAYS = 366
MAX_TRIP_DURATION_VALIDATION_ISSUE = (
    f"must keep trip duration to {MAX_TRIP_DURATION_DAYS} days or fewer"
)
MAX_TRIP_DURATION_DEPENDENCY_MESSAGE = (
    "Database API returned a trip that exceeds TripGenie's maximum supported "
    "duration."
)


def inclusive_trip_day_count(start_date: str, end_date: str) -> int:
    return (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1


def validate_trip_window(
    start_date: str,
    end_date: str,
    *,
    message: str,
) -> None:
    if start_date > end_date:
        raise validation_error(
            message,
            [{"field": "start_date", "issue": "must be on or before end_date"}],
        )

    if inclusive_trip_day_count(start_date, end_date) <= MAX_TRIP_DURATION_DAYS:
        return

    raise validation_error(
        message,
        [{"field": "end_date", "issue": MAX_TRIP_DURATION_VALIDATION_ISSUE}],
    )


def ensure_trip_detail_supported(trip: TripRecord) -> None:
    duration = inclusive_trip_day_count(trip.start_date, trip.end_date)
    if duration <= MAX_TRIP_DURATION_DAYS:
        return

    raise bad_gateway(
        MAX_TRIP_DURATION_DEPENDENCY_MESSAGE,
        [
            {
                "field": "database",
                "issue": (
                    f"trip '{trip.id}' spans {duration} days; maximum supported "
                    f"duration is {MAX_TRIP_DURATION_DAYS} days"
                ),
            },
        ],
    )
