from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

HEALTH_PATH = "/health"
READY_PATH = "/ready"
OPTIONS_PATH = "/api/transport-options"
COMPARE_PATH = "/api/transport-options/compare"
ENTRIES_PATH = "/api/transport-bookings"

SHUTTLE_ID = "transport_2027_zqn_snow_shuttle"
SYDNEY_TRIP = "trip_2026_sydney_long_weekend"
QUEENSTOWN_TRIP = "trip_2027_queenstown_ski_escape"

NEW_OPTION: dict[str, Any] = {
    "type": "bus",
    "provider": "Greyhound",
    "origin": "Canberra",
    "destination": "Sydney",
    "departure_time": "2026-10-01T08:00",
    "arrival_time": "2026-10-01T11:30",
    "price": 48.75,
    "capacity": 40,
    "availability_status": "available",
    "notes": "Express coach service.",
}


def _data(response) -> Any:
    return response.json()["data"]


def _error(response) -> dict[str, Any]:
    return response.json()["error"]


def _detail_fields(response) -> list[str]:
    return [detail["field"] for detail in _error(response)["details"]]


def _create_option(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(OPTIONS_PATH, json=NEW_OPTION | overrides)
    assert response.status_code == 201, response.text
    return _data(response)


# ----------------------------------------------------------------- health


def test_health_reports_the_database_dependency(client: TestClient) -> None:
    body = _data(client.get(HEALTH_PATH))

    assert body["status"] == "ok"
    assert body["service"] == "student-3-backend"
    assert body["dependencies"]["database"]["status"] == "ok"


def test_ready_returns_200_when_the_database_is_reachable(
    client: TestClient,
) -> None:
    response = client.get(READY_PATH)

    assert response.status_code == 200
    assert _data(response)["status"] == "ok"


def test_health_degrades_when_the_database_is_unreachable(
    offline_client: TestClient,
) -> None:
    response = offline_client.get(HEALTH_PATH)

    assert response.status_code == 200
    body = _data(response)
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"]["status"] == "unavailable"


def test_ready_returns_503_when_the_database_is_unreachable(
    offline_client: TestClient,
) -> None:
    response = offline_client.get(READY_PATH)

    assert response.status_code == 503
    assert _data(response)["status"] == "unavailable"


def test_dependency_failure_surfaces_as_503_on_a_data_route(
    offline_client: TestClient,
) -> None:
    response = offline_client.get(OPTIONS_PATH)

    assert response.status_code == 503
    assert _error(response)["code"] == "DEPENDENCY_UNAVAILABLE"


# ---------------------------------------------------------------- options


def test_seeded_options_are_served_through_the_public_api(
    client: TestClient,
) -> None:
    options = _data(client.get(OPTIONS_PATH))

    assert len(options) >= 10
    assert all("seats_remaining" in option for option in options)
    assert all(option["duration_minutes"] > 0 for option in options)


def test_filter_options_by_type_and_route(client: TestClient) -> None:
    options = _data(
        client.get(
            OPTIONS_PATH,
            params={"type": "flight", "origin": "sydney", "destination": "TOKYO"},
        ),
    )

    assert [option["id"] for option in options] == ["transport_2027_jl772_syd_hnd"]


def test_filter_options_by_price_range(client: TestClient) -> None:
    options = _data(
        client.get(OPTIONS_PATH, params={"min_price": "20", "max_price": "50"}),
    )

    assert options
    assert all(20 <= option["price"] <= 50 for option in options)


def test_filter_options_by_departure_window(client: TestClient) -> None:
    options = _data(
        client.get(
            OPTIONS_PATH,
            params={
                "departure_from": "2026-12-01T00:00",
                "departure_to": "2026-12-31T23:59",
            },
        ),
    )

    assert options
    assert all(option["departure_time"].startswith("2026-12") for option in options)


def test_reversed_price_range_is_rejected_by_the_backend(
    client: TestClient,
) -> None:
    response = client.get(
        OPTIONS_PATH,
        params={"min_price": "500", "max_price": "100"},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["min_price"]


def test_reversed_departure_window_is_rejected(client: TestClient) -> None:
    response = client.get(
        OPTIONS_PATH,
        params={
            "departure_from": "2026-12-31T00:00",
            "departure_to": "2026-12-01T00:00",
        },
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["departure_from"]


def test_unsupported_query_parameter_is_rejected(client: TestClient) -> None:
    response = client.get(OPTIONS_PATH, params={"colour": "blue"})

    assert response.status_code == 400
    assert _error(response)["code"] == "BAD_REQUEST"
    assert _detail_fields(response) == ["colour"]


def test_unknown_transport_type_filter_is_rejected(client: TestClient) -> None:
    response = client.get(OPTIONS_PATH, params={"type": "rocket"})

    assert response.status_code == 422
    assert _detail_fields(response) == ["type"]


def test_create_option_returns_the_derived_fields(client: TestClient) -> None:
    created = _create_option(client)

    assert created["id"].startswith("transport_")
    assert created["duration_minutes"] == 210
    assert created["seats_remaining"] == 40


def test_option_round_trips_through_get(client: TestClient) -> None:
    created = _create_option(client, id="transport_backend_round_trip")

    fetched = _data(client.get(f"{OPTIONS_PATH}/transport_backend_round_trip"))
    assert fetched == created


def test_patch_option_recomputes_duration(client: TestClient) -> None:
    created = _create_option(client)
    response = client.patch(
        f"{OPTIONS_PATH}/{created['id']}",
        json={"arrival_time": "2026-10-01T09:00"},
    )

    assert response.status_code == 200
    assert _data(response)["duration_minutes"] == 60


def test_delete_option_without_entries_succeeds(client: TestClient) -> None:
    created = _create_option(client)

    response = client.delete(f"{OPTIONS_PATH}/{created['id']}")

    assert response.status_code == 200
    assert _data(response) == {"id": created["id"], "deleted": True}
    assert client.get(f"{OPTIONS_PATH}/{created['id']}").status_code == 404


def test_delete_option_with_entries_conflicts(client: TestClient) -> None:
    response = client.delete(f"{OPTIONS_PATH}/transport_2026_qf401_mel_syd")

    assert response.status_code == 409
    assert _error(response)["code"] == "CONFLICT"


def test_unknown_option_returns_not_found(client: TestClient) -> None:
    response = client.get(f"{OPTIONS_PATH}/transport_missing_service")

    assert response.status_code == 404
    assert _error(response)["code"] == "NOT_FOUND"


def test_malformed_option_identifier_is_rejected(client: TestClient) -> None:
    response = client.get(f"{OPTIONS_PATH}/not-a-transport-id")

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------ route rule


def test_option_origin_must_differ_from_destination(client: TestClient) -> None:
    response = client.post(
        OPTIONS_PATH,
        json=NEW_OPTION | {"origin": "Sydney", "destination": " sydney "},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["destination"]


def test_car_rental_may_return_to_the_same_depot(client: TestClient) -> None:
    created = _create_option(
        client,
        type="car_rental",
        origin="Hobart Airport",
        destination="Hobart Airport",
        arrival_time="2026-10-05T08:00",
    )

    assert created["type"] == "car_rental"
    assert created["origin"] == created["destination"]


def test_patch_cannot_collapse_a_route_onto_one_place(client: TestClient) -> None:
    created = _create_option(client)

    response = client.patch(
        f"{OPTIONS_PATH}/{created['id']}",
        json={"destination": "Canberra"},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["destination"]


def test_patch_to_car_rental_allows_a_same_place_route(client: TestClient) -> None:
    created = _create_option(client)

    response = client.patch(
        f"{OPTIONS_PATH}/{created['id']}",
        json={"type": "car_rental", "destination": "Canberra"},
    )

    assert response.status_code == 200
    assert _data(response)["destination"] == "Canberra"


# ---------------------------------------------------------------- compare


def test_compare_returns_the_selected_options_in_departure_order(
    client: TestClient,
) -> None:
    options = _data(
        client.get(
            COMPARE_PATH,
            params={"ids": "transport_2027_jl772_syd_hnd,transport_2026_qf401_mel_syd"},
        ),
    )

    assert [option["id"] for option in options] == [
        "transport_2026_qf401_mel_syd",
        "transport_2027_jl772_syd_hnd",
    ]


def test_compare_accepts_repeated_query_parameters(client: TestClient) -> None:
    response = client.get(
        f"{COMPARE_PATH}?ids=transport_2026_qf401_mel_syd&ids={SHUTTLE_ID}",
    )

    assert response.status_code == 200
    assert len(_data(response)) == 2


def test_compare_rejects_an_empty_selection(client: TestClient) -> None:
    response = client.get(COMPARE_PATH)

    assert response.status_code == 422
    assert _detail_fields(response) == ["ids"]


def test_compare_rejects_more_than_four_options(client: TestClient) -> None:
    ids = ",".join(
        [
            "transport_2026_qf401_mel_syd",
            "transport_2026_qf436_syd_mel",
            "transport_2026_vline_mel_geelong",
            "transport_2026_skybus_mel_city",
            SHUTTLE_ID,
        ],
    )
    response = client.get(COMPARE_PATH, params={"ids": ids})

    assert response.status_code == 422
    assert _detail_fields(response) == ["ids"]


def test_compare_rejects_a_repeated_option(client: TestClient) -> None:
    response = client.get(
        COMPARE_PATH,
        params={"ids": f"{SHUTTLE_ID},{SHUTTLE_ID}"},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["ids"]


def test_compare_surfaces_an_unknown_option_rather_than_dropping_it(
    client: TestClient,
) -> None:
    response = client.get(
        COMPARE_PATH,
        params={"ids": f"{SHUTTLE_ID},transport_missing_service"},
    )

    assert response.status_code == 404
    assert _error(response)["code"] == "NOT_FOUND"


def test_compare_rejects_a_malformed_identifier(client: TestClient) -> None:
    response = client.get(COMPARE_PATH, params={"ids": "not-an-id"})

    assert response.status_code == 422
    assert _detail_fields(response) == ["ids"]


# ------------------------------------------------------------ plan entries


def test_seeded_plan_entries_are_served(client: TestClient) -> None:
    entries = _data(client.get(ENTRIES_PATH))

    assert len(entries) >= 10
    assert all("estimated_cost" in entry for entry in entries)
    assert all("traveller_count" in entry for entry in entries)


def test_filter_entries_by_trip_and_status(client: TestClient) -> None:
    entries = _data(
        client.get(
            ENTRIES_PATH,
            params={
                "trip_id": "trip_2026_melbourne_food_trail",
                "booking_status": "pending",
            },
        ),
    )

    assert [entry["id"] for entry in entries] == [
        "booking_2026_melbourne_geelong_train",
    ]


def test_create_entry_derives_the_estimated_cost(client: TestClient) -> None:
    response = client.post(
        ENTRIES_PATH,
        json={
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": 2,
            "booking_date": "2027-05-03",
            "booking_status": "pending",
        },
    )

    assert response.status_code == 201, response.text
    assert _data(response)["estimated_cost"] == 56.00


def test_create_entry_accepts_an_explicit_estimated_cost(
    client: TestClient,
) -> None:
    response = client.post(
        ENTRIES_PATH,
        json={
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": 2,
            "booking_date": "2027-05-03",
            "booking_status": "pending",
            "estimated_cost": 40.00,
        },
    )

    assert response.status_code == 201
    assert _data(response)["estimated_cost"] == 40.00


def test_entry_for_unknown_option_returns_not_found(client: TestClient) -> None:
    response = client.post(
        ENTRIES_PATH,
        json={
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": "transport_missing_service",
            "traveller_count": 1,
            "booking_date": "2027-05-03",
            "booking_status": "pending",
        },
    )

    assert response.status_code == 404


def test_entry_beyond_remaining_capacity_conflicts(client: TestClient) -> None:
    response = client.post(
        ENTRIES_PATH,
        json={
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": 9,
            "booking_date": "2027-05-03",
            "booking_status": "confirmed",
        },
    )

    assert response.status_code == 409
    assert _detail_fields(response) == ["traveller_count"]


def test_entry_after_departure_is_rejected(client: TestClient) -> None:
    response = client.post(
        ENTRIES_PATH,
        json={
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": 1,
            "booking_date": "2027-07-11",
            "booking_status": "pending",
        },
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["booking_date"]


def test_patch_entry_recomputes_the_estimated_cost(client: TestClient) -> None:
    response = client.patch(
        f"{ENTRIES_PATH}/booking_2027_queenstown_transfer",
        json={"traveller_count": 4},
    )

    assert response.status_code == 200
    assert _data(response)["estimated_cost"] == 112.00


def test_delete_entry_succeeds(client: TestClient) -> None:
    response = client.delete(f"{ENTRIES_PATH}/booking_2027_adelaide_airport_bus")

    assert response.status_code == 200
    assert _data(response)["deleted"] is True


def test_entries_for_one_option(client: TestClient) -> None:
    entries = _data(
        client.get(f"{OPTIONS_PATH}/transport_2026_qf401_mel_syd/plan-entries"),
    )

    assert [entry["id"] for entry in entries] == [
        "booking_2026_sydney_outbound_flight",
    ]


def test_unknown_entry_returns_not_found(client: TestClient) -> None:
    response = client.get(f"{ENTRIES_PATH}/booking_missing_reference")

    assert response.status_code == 404


# ------------------------------------------------------- trip transport view


def test_trip_transport_composes_entries_with_their_options(
    client: TestClient,
) -> None:
    summary = _data(client.get(f"/api/trips/{SYDNEY_TRIP}/transport"))

    assert summary["trip_id"] == SYDNEY_TRIP
    assert summary["entry_count"] == 2
    assert summary["active_entry_count"] == 2
    # 189.00 x 2 plus 205.50 x 2
    assert summary["estimated_cost_total"] == 789.00
    assert len(summary["planned"]) == 2
    for planned in summary["planned"]:
        assert planned["entry"]["transport_id"] == planned["option"]["id"]


def test_trip_transport_is_ordered_by_departure(client: TestClient) -> None:
    summary = _data(client.get(f"/api/trips/{SYDNEY_TRIP}/transport"))

    departures = [planned["option"]["departure_time"] for planned in summary["planned"]]
    assert departures == sorted(departures)


def test_trip_transport_excludes_cancelled_entries_from_the_total(
    client: TestClient,
) -> None:
    before = _data(client.get(f"/api/trips/{SYDNEY_TRIP}/transport"))
    assert before["active_entry_count"] == 2

    cancelled = client.patch(
        f"{ENTRIES_PATH}/booking_2026_sydney_outbound_flight",
        json={"booking_status": "cancelled"},
    )
    assert cancelled.status_code == 200

    after = _data(client.get(f"/api/trips/{SYDNEY_TRIP}/transport"))
    assert after["entry_count"] == 2
    assert after["active_entry_count"] == 1
    assert after["estimated_cost_total"] == 411.00


def test_trip_transport_is_empty_for_a_trip_with_no_entries(
    client: TestClient,
) -> None:
    summary = _data(client.get("/api/trips/trip_2030_unplanned_trip/transport"))

    assert summary["entry_count"] == 0
    assert summary["active_entry_count"] == 0
    assert summary["estimated_cost_total"] == 0
    assert summary["planned"] == []


def test_trip_transport_rejects_a_malformed_trip_id(client: TestClient) -> None:
    response = client.get("/api/trips/melbourne/transport")

    assert response.status_code == 422
