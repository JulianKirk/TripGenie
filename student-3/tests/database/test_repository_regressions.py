from __future__ import annotations

from pathlib import Path

import pytest
from student3_database_service.config import Settings
from student3_database_service.errors import ApiError
from student3_database_service.models import (
    TransportOptionCreate,
    TransportOptionUpdate,
)
from student3_database_service.repository import (
    DatabaseService,
    duration_minutes,
)
from student3_database_service.seed_data import SEED_TRANSPORT_OPTIONS

SHUTTLE_ID = "transport_2027_zqn_snow_shuttle"
CANCELLED_TRAIN_ID = "transport_2027_xpt_syd_bne"
CANCELLED_BOOKING_ID = "booking_2027_brisbane_train"


def _new_option(**overrides: object) -> TransportOptionCreate:
    payload: dict[str, object] = {
        "type": "bus",
        "provider": "Greyhound",
        "origin": "Canberra",
        "destination": "Sydney",
        "departure_time": "2026-10-01T08:00",
        "arrival_time": "2026-10-01T11:30",
        "price": 48.75,
        "capacity": 40,
        "availability_status": "available",
    }
    return TransportOptionCreate.model_validate(payload | overrides)


def test_seed_data_meets_the_ten_record_minimum() -> None:
    """Checked on the seed constant, not a live database.

    A failure here is a data problem rather than a query problem, and saying so
    at this level makes that obvious.
    """
    assert len(SEED_TRANSPORT_OPTIONS) >= 10


def test_seed_identifiers_are_unique() -> None:
    option_ids = [option["id"] for option in SEED_TRANSPORT_OPTIONS]

    assert len(set(option_ids)) == len(option_ids)


def test_initialize_is_idempotent(service: DatabaseService) -> None:
    service.initialize()
    service.initialize()

    assert len(service.list_transport_options()) == len(SEED_TRANSPORT_OPTIONS)


def test_seeding_is_skipped_when_the_database_already_has_rows(
    database_path: Path,
) -> None:
    unseeded = DatabaseService(Settings(sqlite_path=database_path, seed_data=False))
    unseeded.initialize()
    unseeded.create_transport_option(_new_option(id="transport_pre_existing_row"))

    seeded = DatabaseService(Settings(sqlite_path=database_path))
    seeded.initialize()

    options = seeded.list_transport_options()
    assert [option["id"] for option in options] == ["transport_pre_existing_row"]


def test_seed_durations_match_the_shared_helper(service: DatabaseService) -> None:
    service.initialize()

    for option in service.list_transport_options():
        assert option["duration_minutes"] == duration_minutes(
            str(option["departure_time"]),
            str(option["arrival_time"]),
            option["departure_utc_offset"],
            option["arrival_utc_offset"],
        )


def test_blank_notes_are_stored_as_null(service: DatabaseService) -> None:
    service.initialize()
    created = service.create_transport_option(
        _new_option(id="transport_blank_notes_case", notes="   "),
    )

    assert created["notes"] is None


def test_zero_length_journeys_are_rejected(service: DatabaseService) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.create_transport_option(
            _new_option(arrival_time="2026-10-01T08:00"),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.details[0]["field"] == "arrival_time"


def test_a_two_month_car_hire_is_accepted(service: DatabaseService) -> None:
    service.initialize()

    created = service.create_transport_option(
        _new_option(
            id="transport_long_term_hire",
            type="car_rental",
            departure_time="2026-10-01T08:00",
            arrival_time="2026-12-01T08:00",
        ),
    )

    assert created["duration_minutes"] == 61 * 24 * 60


def test_journeys_longer_than_ninety_days_are_rejected(
    service: DatabaseService,
) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.create_transport_option(
            _new_option(
                departure_time="2026-10-01T08:00",
                arrival_time="2027-02-01T08:00",
            ),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.details[0]["field"] == "arrival_time"


def test_option_update_requires_at_least_one_field(
    service: DatabaseService,
) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.update_transport_option(SHUTTLE_ID, TransportOptionUpdate())

    assert excinfo.value.status_code == 422
    assert excinfo.value.details[0]["field"] == "body"


def test_cross_timezone_duration_uses_utc_not_wall_clock(
    service: DatabaseService,
) -> None:
    service.initialize()
    flight = service.get_transport_option("transport_2027_jl772_syd_hnd")

    # 21:35 Sydney (UTC+11) to 05:55 Tokyo (UTC+9) reads as 8h20 on the two
    # clocks but is really 10h20 in the air.
    naive = duration_minutes(
        str(flight["departure_time"]),
        str(flight["arrival_time"]),
    )
    assert naive == 500
    assert flight["duration_minutes"] == 620


def test_dateline_crossing_may_land_at_an_earlier_local_time(
    service: DatabaseService,
) -> None:
    service.initialize()

    created = service.create_transport_option(
        _new_option(
            id="transport_dateline_case",
            type="flight",
            origin="Sydney",
            destination="Los Angeles",
            departure_time="2026-11-02T11:00",
            arrival_time="2026-11-02T06:30",
            departure_utc_offset=660,
            arrival_utc_offset=-420,
        ),
    )

    # Lands at 06:30 local on the same date it left at 11:00 local, which the
    # old departure_time < arrival_time table constraint would have refused.
    assert created["arrival_time"] < created["departure_time"]
    assert created["duration_minutes"] == 810


def test_offsets_must_be_supplied_as_a_pair(service: DatabaseService) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.create_transport_option(
            _new_option(id="transport_half_offset", departure_utc_offset=600),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.details[0]["field"] == "departure_utc_offset"

