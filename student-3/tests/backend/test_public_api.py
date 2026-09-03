from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

HEALTH_PATH = "/health"
READY_PATH = "/ready"
OPTIONS_PATH = "/api/transport-options"
COMPARE_PATH = "/api/transport-options/compare"

SHUTTLE_ID = "transport_2027_zqn_snow_shuttle"
FLIGHT_ID = "transport_2026_qf401_mel_syd"
HIRE_ID = "transport_2026_europcar_gold_coast"
SOLD_OUT_ID = "transport_2026_sq232_syd_sin"
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


def _selection(response, trip_id: str) -> dict[str, Any]:
    """One trip's row out of a tick-list response."""
    rows = _data(response)["itineraries"]
    return next(row for row in rows if row["trip_id"] == trip_id)


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


# ------------------------------------------------------- trip transport view


def test_trip_transport_is_ordered_by_departure(client: TestClient) -> None:
    summary = _data(client.get(f"/api/trips/{SYDNEY_TRIP}/transport"))

    departures = [planned["option"]["departure_time"] for planned in summary["planned"]]
    assert departures == sorted(departures)


def test_trip_transport_rejects_a_malformed_trip_id(client: TestClient) -> None:
    response = client.get("/api/trips/melbourne/transport")

    assert response.status_code == 422


# ------------------------------------------------------------- selections
#
# Which transport belongs to which trip is stored by the itinerary service.
# These pin the parts this service is still answerable for: pricing a
# selection, refusing one that cannot be honoured, and never inventing a
# seat count it cannot know.


def test_the_tick_list_offers_every_trip(client: TestClient) -> None:
    body = _data(client.get(f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries"))

    assert len(body["itineraries"]) == 2
    assert not any(row["selected"] for row in body["itineraries"])
    assert body["seats_remaining"] == 180


def test_adding_marks_the_trip_and_prices_it(client: TestClient) -> None:
    response = client.put(
        f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 3},
    )

    assert response.status_code == 200, response.text
    row = _selection(response, QUEENSTOWN_TRIP)
    assert row["selected"] is True
    assert row["traveller_count"] == 3
    assert row["estimated_cost"] == 567.00
    assert _data(response)["seats_remaining"] == 177


def test_a_per_vehicle_option_is_not_multiplied(client: TestClient) -> None:
    """A car hire costs the same for one traveller or five.

    The bug this prevents is arithmetic, not presentation: multiplying a
    whole-vehicle rate by the party size overstates a trip's transport budget,
    which Student 5's feature then reports as fact.
    """
    response = client.put(
        f"{OPTIONS_PATH}/{HIRE_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 4},
    )

    row = _selection(response, QUEENSTOWN_TRIP)
    assert row["estimated_cost"] == 612.00


def test_adding_the_same_trip_twice_replaces_rather_than_duplicates(
    client: TestClient,
) -> None:
    """PUT is idempotent, so a double submit cannot double-count a party."""
    path = f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries/{QUEENSTOWN_TRIP}"
    client.put(path, json={"traveller_count": 2})
    response = client.put(path, json={"traveller_count": 5})

    body = _data(response)
    assert sum(1 for row in body["itineraries"] if row["selected"]) == 1
    assert _selection(response, QUEENSTOWN_TRIP)["traveller_count"] == 5
    assert body["seats_remaining"] == 175


def test_a_party_larger_than_the_service_is_refused(client: TestClient) -> None:
    response = client.put(
        f"{OPTIONS_PATH}/{HIRE_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 99},
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CONFLICT"
    assert "seat(s) remain" in error["details"][0]["issue"]


def test_capacity_counts_other_trips_but_not_this_one(client: TestClient) -> None:
    """Re-sizing a party must not be blocked by the party it replaces.

    The naive check sums every selection including the one being changed, so
    raising 4 travellers to 5 on a 5-seat vehicle would wrongly need 9 seats.
    """
    client.put(
        f"{OPTIONS_PATH}/{HIRE_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 4},
    )

    response = client.put(
        f"{OPTIONS_PATH}/{HIRE_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 5},
    )

    assert response.status_code == 200, response.text


def test_an_unusable_option_cannot_be_added(client: TestClient) -> None:
    response = client.put(
        f"{OPTIONS_PATH}/{SOLD_OUT_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 1},
    )

    assert response.status_code == 409
    assert "sold_out" in response.json()["error"]["details"][0]["issue"]


def test_removing_gives_the_seats_back(client: TestClient) -> None:
    client.put(
        f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 3},
    )

    response = client.delete(
        f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries/{QUEENSTOWN_TRIP}",
    )

    assert response.status_code == 200
    assert _selection(response, QUEENSTOWN_TRIP)["selected"] is False
    assert _data(response)["seats_remaining"] == 180


def test_seats_are_unknown_rather_than_zero_when_the_itinerary_is_down(
    settings: Settings,
    database_transport: httpx.MockTransport,
    unreachable_trips_transport: httpx.MockTransport,
) -> None:
    """None, not 0. Reporting a full service during an outage would be a lie."""
    app = create_app(
        settings,
        transport=database_transport,
        trips_transport=unreachable_trips_transport,
    )
    with TestClient(app) as client:
        option = _data(client.get(f"{OPTIONS_PATH}/{FLIGHT_ID}"))

    assert option["seats_remaining"] is None


def test_the_trip_view_keeps_the_shape_student_5_reads(client: TestClient) -> None:
    """Selections moved, but this contract must not.

    Student 5's budget feature reads these two fields off this route. It should
    not have to know that the underlying rows now live somewhere else.
    """
    client.put(
        f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 2},
    )

    body = _data(client.get(f"/api/trips/{QUEENSTOWN_TRIP}/transport"))

    assert body["estimated_cost_total"] == 378.00
    assert body["currency"] == "AUD"
    assert body["entry_count"] == 1
    assert body["active_entry_count"] == 1
    assert body["planned"][0]["option"]["id"] == FLIGHT_ID


def test_an_option_a_trip_holds_cannot_be_deleted(client: TestClient) -> None:
    """The guard a foreign key used to give, re-made across the boundary.

    Without it, deleting an option leaves Student 1 holding rows that point at
    nothing, and a trip page showing a journey it cannot name.
    """
    client.put(
        f"{OPTIONS_PATH}/{FLIGHT_ID}/itineraries/{QUEENSTOWN_TRIP}",
        json={"traveller_count": 2},
    )

    response = client.delete(f"{OPTIONS_PATH}/{FLIGHT_ID}")

    assert response.status_code == 409
    assert "still hold it" in response.json()["error"]["details"][0]["issue"]


def test_an_unheld_option_deletes_normally(client: TestClient) -> None:
    assert client.delete(f"{OPTIONS_PATH}/{FLIGHT_ID}").status_code == 200
