from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from student3_database_service.config import Settings
from student3_database_service.errors import ApiError
from student3_database_service.models import (
    CAPACITY_CONSUMING_BOOKING_STATUSES,
    BookingStatus,
    TransportBookingCreate,
    TransportBookingUpdate,
    TransportOptionCreate,
    TransportOptionUpdate,
)
from student3_database_service.repository import (
    DatabaseService,
    default_total_cost,
    duration_minutes,
)
from student3_database_service.seed_data import (
    SEED_TRANSPORT_BOOKINGS,
    SEED_TRANSPORT_OPTIONS,
)

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
    assert len(SEED_TRANSPORT_OPTIONS) >= 10
    assert len(SEED_TRANSPORT_BOOKINGS) >= 10


def test_seed_identifiers_are_unique() -> None:
    option_ids = [option["id"] for option in SEED_TRANSPORT_OPTIONS]
    booking_ids = [booking["id"] for booking in SEED_TRANSPORT_BOOKINGS]

    assert len(set(option_ids)) == len(option_ids)
    assert len(set(booking_ids)) == len(booking_ids)


def test_seed_bookings_reference_seeded_options() -> None:
    option_ids = {option["id"] for option in SEED_TRANSPORT_OPTIONS}

    for booking in SEED_TRANSPORT_BOOKINGS:
        assert booking["transport_id"] in option_ids


def test_seed_bookings_never_exceed_option_capacity() -> None:
    capacity = {
        option["id"]: int(option["capacity"]) for option in SEED_TRANSPORT_OPTIONS
    }
    booked: dict[str, int] = {}

    for booking in SEED_TRANSPORT_BOOKINGS:
        if BookingStatus(booking["booking_status"]) in (
            CAPACITY_CONSUMING_BOOKING_STATUSES
        ):
            transport_id = str(booking["transport_id"])
            booked[transport_id] = booked.get(transport_id, 0) + int(
                booking["passenger_count"],
            )

    for transport_id, seats in booked.items():
        assert seats <= capacity[transport_id]


def test_seed_bookings_are_made_before_departure() -> None:
    departures = {
        option["id"]: str(option["departure_time"])[:10]
        for option in SEED_TRANSPORT_OPTIONS
    }

    for booking in SEED_TRANSPORT_BOOKINGS:
        assert booking["booking_date"] <= departures[booking["transport_id"]]


def test_initialize_is_idempotent(service: DatabaseService) -> None:
    service.initialize()
    service.initialize()

    assert len(service.list_transport_options()) == len(SEED_TRANSPORT_OPTIONS)
    assert len(service.list_transport_bookings()) == len(SEED_TRANSPORT_BOOKINGS)


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


def test_seed_totals_match_the_per_passenger_default(
    service: DatabaseService,
) -> None:
    service.initialize()
    prices = {
        option["id"]: float(option["price"])
        for option in service.list_transport_options()
    }
    overridden = {"booking_2026_gold_coast_car_hire"}

    for booking in service.list_transport_bookings():
        if booking["id"] in overridden:
            continue

        assert booking["total_cost"] == default_total_cost(
            prices[booking["transport_id"]],
            int(booking["passenger_count"]),
        )


def test_foreign_key_enforcement_is_enabled(
    service: DatabaseService,
    database_path: Path,
) -> None:
    service.initialize()

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO transport_bookings (
                id, trip_id, transport_id, passenger_count,
                booking_date, total_cost, booking_status, notes
            ) VALUES (
                'booking_orphan_row', 'trip_2026_orphan', 'transport_missing_row',
                1, '2026-01-01', 10.0, 'pending', NULL
            )
            """,
        )
    connection.close()


def test_cancelled_bookings_do_not_consume_capacity(
    service: DatabaseService,
) -> None:
    service.initialize()
    shuttle = service.get_transport_option(SHUTTLE_ID)
    remaining = int(shuttle["capacity"]) - 3

    service.update_transport_booking(
        "booking_2027_queenstown_transfer",
        TransportBookingUpdate(booking_status=BookingStatus.CANCELLED),
    )

    created = service.create_transport_booking(
        TransportBookingCreate.model_validate(
            {
                "trip_id": "trip_2027_queenstown_ski_escape",
                "transport_id": SHUTTLE_ID,
                "passenger_count": remaining + 3,
                "booking_date": "2027-05-03",
                "booking_status": "confirmed",
            },
        ),
    )

    assert created["passenger_count"] == int(shuttle["capacity"])


def test_reactivating_a_booking_on_a_cancelled_option_is_rejected(
    service: DatabaseService,
) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.update_transport_booking(
            CANCELLED_BOOKING_ID,
            TransportBookingUpdate(booking_status=BookingStatus.CONFIRMED),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.details[0]["field"] == "transport_id"


def test_editing_notes_on_a_cancelled_option_booking_still_works(
    service: DatabaseService,
) -> None:
    service.initialize()

    updated = service.update_transport_booking(
        CANCELLED_BOOKING_ID,
        TransportBookingUpdate(notes="Refund processed."),
    )

    assert updated["notes"] == "Refund processed."
    assert updated["booking_status"] == "cancelled"


def test_completed_booking_on_a_sold_out_option_can_be_edited(
    service: DatabaseService,
) -> None:
    service.initialize()

    updated = service.update_transport_booking(
        "booking_2026_singapore_flight",
        TransportBookingUpdate(notes="Boarding pass archived."),
    )

    assert updated["notes"] == "Boarding pass archived."


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


def test_deleting_an_option_with_bookings_is_blocked(
    service: DatabaseService,
) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.delete_transport_option(CANCELLED_TRAIN_ID)

    assert excinfo.value.status_code == 409

    service.delete_transport_booking(CANCELLED_BOOKING_ID)
    assert service.delete_transport_option(CANCELLED_TRAIN_ID)["deleted"] is True


def test_moving_a_booking_to_another_option_revalidates_capacity(
    service: DatabaseService,
) -> None:
    service.initialize()
    service.create_transport_option(
        _new_option(
            id="transport_single_seat_shuttle",
            capacity=1,
            departure_time="2027-07-09T10:00",
            arrival_time="2027-07-09T10:45",
        ),
    )

    with pytest.raises(ApiError) as excinfo:
        service.update_transport_booking(
            "booking_2027_queenstown_transfer",
            TransportBookingUpdate(transport_id="transport_single_seat_shuttle"),
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.details[0]["field"] == "passenger_count"


def test_option_update_requires_at_least_one_field(
    service: DatabaseService,
) -> None:
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.update_transport_option(SHUTTLE_ID, TransportOptionUpdate())

    assert excinfo.value.status_code == 422
    assert excinfo.value.details[0]["field"] == "body"


def test_overridden_total_cost_survives_unrelated_updates(
    service: DatabaseService,
) -> None:
    service.initialize()

    updated = service.update_transport_booking(
        "booking_2026_gold_coast_car_hire",
        TransportBookingUpdate(notes="Toll pass added."),
    )

    assert updated["total_cost"] == 612.00


def test_changing_passenger_count_rederives_an_overridden_total(
    service: DatabaseService,
) -> None:
    service.initialize()

    updated = service.update_transport_booking(
        "booking_2026_gold_coast_car_hire",
        TransportBookingUpdate(passenger_count=2),
    )

    assert updated["total_cost"] == default_total_cost(612.00, 2)


def test_an_explicit_total_cost_wins_over_the_rederived_default(
    service: DatabaseService,
) -> None:
    service.initialize()

    updated = service.update_transport_booking(
        "booking_2026_gold_coast_car_hire",
        TransportBookingUpdate(passenger_count=2, total_cost=612.00),
    )

    assert updated["total_cost"] == 612.00


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


def test_seats_remaining_tracks_live_bookings(service: DatabaseService) -> None:
    service.initialize()

    shuttle = service.get_transport_option(SHUTTLE_ID)
    assert shuttle["capacity"] == 11
    assert shuttle["seats_remaining"] == 8

    service.update_transport_booking(
        "booking_2027_queenstown_transfer",
        TransportBookingUpdate(booking_status=BookingStatus.CANCELLED),
    )

    assert service.get_transport_option(SHUTTLE_ID)["seats_remaining"] == 11


def test_seats_remaining_is_never_negative(service: DatabaseService) -> None:
    service.initialize()

    for option in service.list_transport_options():
        assert option["seats_remaining"] >= 0
        assert option["seats_remaining"] <= option["capacity"]


def test_seats_remaining_is_not_a_stored_column(
    service: DatabaseService,
    database_path: Path,
) -> None:
    service.initialize()

    connection = sqlite3.connect(database_path)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(transport_options)")
    }
    connection.close()

    assert "seats_remaining" not in columns
    assert {"departure_utc_offset", "arrival_utc_offset"} <= columns


def test_default_total_cost_is_exact_in_cents() -> None:
    # 0.1 * 3 is 0.30000000000000004 in binary floating point.
    assert default_total_cost(0.10, 3) == 0.30
    assert default_total_cost(19.99, 7) == 139.93
    assert default_total_cost(48.75, 2) == 97.50
