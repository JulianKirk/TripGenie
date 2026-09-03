from __future__ import annotations

from datetime import date

from .errors import bad_gateway, validation_error
from .models import TripRecord

MAX_TRIP_DURATION_DAYS = 366
MAX_TRIP_DURATION_VALIDATION_ISSUE = (
    f"must keep trip duration to {MAX_TRIP_DURATION_DAYS} days or fewer"
)
MAX_TRIP_DURATION_DEPENDENCY_MESSAGE = (
    "Database API returned a trip that exceeds TripGenie's maximum supported duration."
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


def validate_stay_window(
    trip: TripRecord,
    check_in: str,
    check_out: str | None,
    check_in_time: str | None = None,
    check_out_time: str | None = None,
    *,
    message: str,
) -> None:
    """A stay has to happen while the trip is happening.

    The same rule an itinerary item already obeys: nothing on a trip may fall
    outside the trip's own dates. The ordering of the two stay dates is the
    record model's job, not this one's -- it holds whether or not there is a
    trip to check against.

    ISO dates compare correctly as strings, which is what validate_trip_window
    above already relies on.
    """
    window = f"{trip.start_date} to {trip.end_date}"
    for field, value in (("date", check_in), ("check_out", check_out)):
        if value is None:
            continue
        if value < trip.start_date or value > trip.end_date:
            raise validation_error(
                message,
                [{"field": field, "issue": f"must fall inside the trip ({window})"}],
            )

    # A one-day stay is only a stay if it ends after it starts, and on a single
    # date the times are the only thing that says so. Checked here rather than
    # on the record alone so a bad pair is a 422 about the request, not a 502
    # about the answer.
    if (
        check_out == check_in
        and check_in_time
        and check_out_time
        and check_out_time <= check_in_time
    ):
        raise validation_error(
            # Its own message: the dates are fine here, so reusing the caller's
            # "must fall inside the trip" would send the user to correct the
            # one thing that is not wrong.
            "A same-day stay must check out after it checks in.",
            [
                {
                    "field": "check_out_time",
                    "issue": "must be after check_in_time on a same-day stay",
                },
            ],
        )
