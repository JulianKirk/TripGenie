from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

HEALTH_PATH = "/internal/health"
OPTIONS_PATH = "/internal/transport-options"
BOOKINGS_PATH = "/internal/transport-bookings"

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
    payload = NEW_OPTION | overrides
    response = client.post(OPTIONS_PATH, json=payload)
    assert response.status_code == 201, response.text
    return _data(response)


def test_health_reports_service_metadata(client: TestClient) -> None:
    response = client.get(HEALTH_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "student-3-database"
    assert body["sqlite_path"].endswith("tripgenie.db")


def test_seed_data_meets_minimum_record_requirement(client: TestClient) -> None:
    """The specification asks for at least ten records per table.

    Only the catalogue is checked now: transport selections moved to the
    itinerary service, so this database has one domain table. `schema_metadata`
    is internal bookkeeping rather than domain data and is excluded
    deliberately, which the Release 0 evidence records.
    """
    options = client.get("/internal/transport-options").json()["data"]

    assert len(options) >= 10


def test_options_are_ordered_by_departure_then_price(client: TestClient) -> None:
    options = _data(client.get(OPTIONS_PATH))

    keys = [
        (option["departure_time"], option["price"], option["id"])
        for option in options
    ]
    assert keys == sorted(keys)


def test_seed_options_carry_derived_duration(client: TestClient) -> None:
    options = _data(client.get(OPTIONS_PATH))

    for option in options:
        assert option["duration_minutes"] > 0

    shuttle = next(
        option
        for option in options
        if option["id"] == "transport_2027_zqn_snow_shuttle"
    )
    assert shuttle["duration_minutes"] == 35


def test_filter_options_by_type(client: TestClient) -> None:
    options = _data(client.get(OPTIONS_PATH, params={"type": "ferry"}))

    assert options
    assert {option["type"] for option in options} == {"ferry"}


def test_filter_options_by_route_is_case_insensitive(client: TestClient) -> None:
    options = _data(
        client.get(
            OPTIONS_PATH,
            params={"origin": "sydney", "destination": "TOKYO"},
        ),
    )

    assert [option["id"] for option in options] == ["transport_2027_jl772_syd_hnd"]


def test_filter_options_by_provider_and_availability(client: TestClient) -> None:
    options = _data(
        client.get(
            OPTIONS_PATH,
            params={"provider": "Qantas", "availability_status": "available"},
        ),
    )

    assert options
    for option in options:
        assert option["provider"] == "Qantas"
        assert option["availability_status"] == "available"


def test_filter_options_by_price_range(client: TestClient) -> None:
    options = _data(
        client.get(OPTIONS_PATH, params={"min_price": "20", "max_price": "50"}),
    )

    assert options
    for option in options:
        assert 20 <= option["price"] <= 50


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
    for option in options:
        assert option["departure_time"].startswith("2026-12")


def test_price_range_must_be_ordered(client: TestClient) -> None:
    response = client.get(
        OPTIONS_PATH,
        params={"min_price": "500", "max_price": "100"},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["min_price"]


def test_departure_window_must_be_ordered(client: TestClient) -> None:
    response = client.get(
        OPTIONS_PATH,
        params={
            "departure_from": "2026-12-31T00:00",
            "departure_to": "2026-12-01T00:00",
        },
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["departure_from"]


def test_unknown_transport_type_filter_is_rejected(client: TestClient) -> None:
    response = client.get(OPTIONS_PATH, params={"type": "rocket"})

    assert response.status_code == 422
    assert _detail_fields(response) == ["type"]


def test_unsupported_query_parameter_is_rejected(client: TestClient) -> None:
    response = client.get(OPTIONS_PATH, params={"colour": "blue"})

    assert response.status_code == 400
    assert _error(response)["code"] == "BAD_REQUEST"
    assert _detail_fields(response) == ["colour"]


def test_create_option_derives_duration(client: TestClient) -> None:
    created = _create_option(client)

    assert created["id"].startswith("transport_")
    assert created["duration_minutes"] == 210
    assert created["price"] == 48.75


def test_create_option_accepts_explicit_identifier(client: TestClient) -> None:
    created = _create_option(client, id="transport_2026_canberra_express")

    assert created["id"] == "transport_2026_canberra_express"


def test_duplicate_option_identifier_conflicts(client: TestClient) -> None:
    _create_option(client, id="transport_2026_canberra_express")
    response = client.post(
        OPTIONS_PATH,
        json=NEW_OPTION | {"id": "transport_2026_canberra_express"},
    )

    assert response.status_code == 409
    assert _error(response)["code"] == "CONFLICT"


def test_arrival_before_departure_is_rejected(client: TestClient) -> None:
    response = client.post(
        OPTIONS_PATH,
        json=NEW_OPTION | {"arrival_time": "2026-10-01T07:00"},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["arrival_time"]


def test_price_with_more_than_two_decimals_is_rejected(client: TestClient) -> None:
    response = client.post(OPTIONS_PATH, json=NEW_OPTION | {"price": 10.123})

    assert response.status_code == 422
    assert _detail_fields(response) == ["price"]


def test_unknown_option_returns_not_found(client: TestClient) -> None:
    response = client.get(f"{OPTIONS_PATH}/transport_missing_service")

    assert response.status_code == 404
    assert _error(response)["code"] == "NOT_FOUND"


def test_malformed_option_identifier_is_rejected(client: TestClient) -> None:
    response = client.get(f"{OPTIONS_PATH}/not-a-transport-id")

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


def test_patch_option_recomputes_duration(client: TestClient) -> None:
    created = _create_option(client)
    response = client.patch(
        f"{OPTIONS_PATH}/{created['id']}",
        json={"arrival_time": "2026-10-01T09:00"},
    )

    assert response.status_code == 200
    assert _data(response)["duration_minutes"] == 60


def test_patch_option_requires_at_least_one_field(client: TestClient) -> None:
    created = _create_option(client)
    response = client.patch(f"{OPTIONS_PATH}/{created['id']}", json={})

    assert response.status_code == 422
    assert _detail_fields(response) == ["body"]


def test_patch_option_rejects_unknown_field(client: TestClient) -> None:
    created = _create_option(client)
    response = client.patch(
        f"{OPTIONS_PATH}/{created['id']}",
        json={"seat_pitch": 32},
    )

    assert response.status_code == 422


def test_delete_option_without_bookings_succeeds(client: TestClient) -> None:
    created = _create_option(client)
    response = client.delete(f"{OPTIONS_PATH}/{created['id']}")

    assert response.status_code == 200
    assert _data(response) == {"id": created["id"], "deleted": True}
    assert client.get(f"{OPTIONS_PATH}/{created['id']}").status_code == 404


def test_list_bookings_for_unknown_option_returns_not_found(
    client: TestClient,
) -> None:
    response = client.get(f"{OPTIONS_PATH}/transport_missing_service/bookings")

    assert response.status_code == 404


def test_create_option_accepts_utc_offsets(client: TestClient) -> None:
    created = _create_option(
        client,
        id="transport_offset_api_case",
        departure_utc_offset=600,
        arrival_utc_offset=480,
    )

    assert created["departure_utc_offset"] == 600
    assert created["arrival_utc_offset"] == 480
    # 08:00 +10:00 to 11:30 +08:00 is 5h30, not the 3h30 the clocks suggest.
    assert created["duration_minutes"] == 330


def test_lone_utc_offset_is_rejected(client: TestClient) -> None:
    response = client.post(
        OPTIONS_PATH,
        json=NEW_OPTION | {"departure_utc_offset": 600},
    )

    assert response.status_code == 422
    assert _detail_fields(response) == ["departure_utc_offset"]


def test_out_of_range_utc_offset_is_rejected(client: TestClient) -> None:
    response = client.post(
        OPTIONS_PATH,
        json=NEW_OPTION | {"departure_utc_offset": 900, "arrival_utc_offset": 0},
    )

    assert response.status_code == 422


def test_seats_remaining_is_read_only(client: TestClient) -> None:
    response = client.post(OPTIONS_PATH, json=NEW_OPTION | {"seats_remaining": 99})

    assert response.status_code == 422


def test_duration_minutes_is_read_only(client: TestClient) -> None:
    response = client.post(OPTIONS_PATH, json=NEW_OPTION | {"duration_minutes": 5})

    assert response.status_code == 422
