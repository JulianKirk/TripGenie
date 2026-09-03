from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

SHUTTLE_ID = "transport_2027_zqn_snow_shuttle"
FLIGHT_ID = "transport_2026_qf401_mel_syd"
TOKYO_ID = "transport_2027_jl772_syd_hnd"
BOOKED_ENTRY = "booking_2027_queenstown_transfer"
SYDNEY_TRIP = "trip_2026_sydney_long_weekend"
QUEENSTOWN_TRIP = "trip_2027_queenstown_ski_escape"

NEW_OPTION: dict[str, str] = {
    "id": "",
    "type": "bus",
    "provider": "Greyhound",
    "origin": "Canberra",
    "destination": "Sydney",
    "departure_time": "2026-10-01T08:00",
    "arrival_time": "2026-10-01T11:30",
    "departure_utc_offset": "",
    "arrival_utc_offset": "",
    "price": "48.75",
    "capacity": "40",
    "availability_status": "available",
    "notes": "Express coach service.",
}

NEW_ENTRY: dict[str, str] = {
    "id": "",
    "trip_id": QUEENSTOWN_TRIP,
    "transport_id": SHUTTLE_ID,
    "traveller_count": "2",
    "booking_date": "2027-05-03",
    "estimated_cost": "",
    "booking_status": "pending",
    "notes": "",
}


def _post(client: TestClient, path: str, data: dict[str, Any]) -> Any:
    return client.post(path, data=data, follow_redirects=False)


# ------------------------------------------------------------------ operations


def test_health_reports_the_backend_dependency(client: TestClient) -> None:
    body = client.get("/health").json()["data"]

    assert body["status"] == "ok"
    assert body["service"] == "student-3-frontend"
    assert body["dependencies"]["backend"]["status"] == "ok"


def test_ready_returns_200_when_the_backend_is_reachable(
    client: TestClient,
) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_health_degrades_when_the_backend_is_unreachable(
    offline_client: TestClient,
) -> None:
    response = offline_client.get("/health")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "degraded"
    assert body["dependencies"]["backend"]["status"] == "unavailable"


def test_ready_returns_503_when_the_backend_is_unreachable(
    offline_client: TestClient,
) -> None:
    response = offline_client.get("/ready")

    assert response.status_code == 503


def test_browse_shows_an_error_panel_when_the_backend_is_down(
    offline_client: TestClient,
) -> None:
    response = offline_client.get("/")

    assert response.status_code == 200
    assert "Transport options are unavailable" in response.text
    assert "DEPENDENCY_UNAVAILABLE" in response.text
    assert "Try again" in response.text


def test_static_css_is_served(client: TestClient) -> None:
    response = client.get("/static/css/styles.css")

    assert response.status_code == 200
    assert "app-shell" in response.text


# --------------------------------------------------------------------- browse


def test_browse_lists_the_seeded_options(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "14 option(s)" in response.text
    assert "Queenstown Airport" in response.text
    assert "Melbourne" in response.text


def test_browse_shows_derived_duration_and_seats(client: TestClient) -> None:
    response = client.get("/")

    # 35 minutes for the Queenstown shuttle, 8 of 11 seats left.
    assert "35m" in response.text
    assert "8 / 11" in response.text


def test_browse_marks_a_cross_timezone_leg(client: TestClient) -> None:
    response = client.get("/")

    assert "10h 20m" in response.text
    assert 'title="Measured in UTC across time zones"' in response.text


def test_browse_filters_by_route(client: TestClient) -> None:
    response = client.get("/", params={"origin": "sydney", "destination": "Tokyo"})

    assert response.status_code == 200
    assert "1 option(s) matching your filters" in response.text
    assert "Japan Airlines" in response.text
    assert "Greyhound" not in response.text


def test_browse_filters_by_price_range(client: TestClient) -> None:
    response = client.get("/", params={"min_price": "20", "max_price": "50"})

    assert "3 option(s) matching your filters" in response.text


def test_browse_blank_filters_are_not_forwarded(client: TestClient) -> None:
    """An untouched filter form must not be sent as blank query parameters.

    The backend rejects a blank value as invalid rather than treating it as
    unset, so a plain "Apply filters" submit would 422 if the frontend passed
    empty strings through.
    """
    response = client.get(
        "/",
        params={
            "type": "",
            "provider": "",
            "origin": "",
            "destination": "",
            "availability_status": "",
            "min_price": "",
            "max_price": "",
            "departure_from": "",
            "departure_to": "",
        },
    )

    assert response.status_code == 200
    assert "14 option(s)" in response.text


def test_browse_reports_a_reversed_price_range(client: TestClient) -> None:
    response = client.get("/", params={"min_price": "500", "max_price": "100"})

    assert response.status_code == 200
    assert "must not be greater than max_price" in response.text


def test_browse_empty_filter_result_explains_itself(client: TestClient) -> None:
    response = client.get("/", params={"origin": "Nowhere"})

    assert "No transport options match those filters" in response.text


# --------------------------------------------------------------- option detail


def test_option_detail_shows_the_plan_entries(client: TestClient) -> None:
    response = client.get(f"/options/{FLIGHT_ID}")

    assert response.status_code == 200
    assert "Melbourne" in response.text
    assert SYDNEY_TRIP in response.text
    assert "In the itinerary" in response.text


def test_option_detail_explains_availability_versus_seats(
    client: TestClient,
) -> None:
    response = client.get("/options/transport_2026_sq232_syd_sin")

    assert "Sold Out" in response.text
    assert "252 of 253" in response.text
    assert "declared by the operator" in response.text


def test_unknown_option_renders_an_error_panel(client: TestClient) -> None:
    response = client.get("/options/transport_missing_service")

    assert response.status_code == 200
    assert "Transport option unavailable" in response.text
    assert "NOT_FOUND" in response.text


def test_malformed_option_id_renders_an_error_panel(client: TestClient) -> None:
    response = client.get("/options/not-an-id")

    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text


# ----------------------------------------------------------------- option CRUD


def test_create_option_redirects_to_the_new_record(client: TestClient) -> None:
    response = _post(client, "/options", NEW_OPTION | {"id": "transport_ui_created"})

    assert response.status_code == 303
    assert response.headers["location"] == "/options/transport_ui_created"

    detail = client.get("/options/transport_ui_created")
    assert detail.status_code == 200
    assert "Greyhound" in detail.text
    assert "3h 30m" in detail.text


def test_create_option_generates_an_id_when_blank(client: TestClient) -> None:
    response = _post(client, "/options", NEW_OPTION)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/options/transport_")


def test_create_option_replays_backend_validation_errors(
    client: TestClient,
) -> None:
    response = _post(client, "/options", NEW_OPTION | {"price": "10.123"})

    assert response.status_code == 200
    assert "must have at most 2 decimal places" in response.text
    # The submitted value is preserved so the user does not retype the form.
    assert 'value="10.123"' in response.text


def test_create_option_replays_the_route_rule(client: TestClient) -> None:
    response = _post(
        client,
        "/options",
        NEW_OPTION | {"origin": "Sydney", "destination": "sydney"},
    )

    assert response.status_code == 200
    assert "must differ from origin" in response.text


def test_create_option_rejects_a_lone_utc_offset(client: TestClient) -> None:
    response = _post(client, "/options", NEW_OPTION | {"departure_utc_offset": "600"})

    assert response.status_code == 200
    assert "must be provided together with arrival_utc_offset" in response.text


def test_edit_option_form_is_prefilled(client: TestClient) -> None:
    response = client.get(f"/options/{SHUTTLE_ID}/edit")

    assert response.status_code == 200
    assert 'value="Queenstown Snow Shuttle"' in response.text
    assert 'value="28.00"' in response.text
    # The identifier field is not offered on an edit.
    assert 'name="id"' not in response.text


def test_update_option_redirects_back_to_the_detail(client: TestClient) -> None:
    form = client.get(f"/options/{SHUTTLE_ID}/edit")
    assert form.status_code == 200

    response = _post(
        client,
        f"/options/{SHUTTLE_ID}/edit",
        NEW_OPTION
        | {
            "id": SHUTTLE_ID,
            "type": "transfer",
            "provider": "Queenstown Snow Shuttle",
            "origin": "Queenstown Airport",
            "destination": "Queenstown Town Centre",
            "departure_time": "2027-07-10T14:20",
            "arrival_time": "2027-07-10T15:10",
            "price": "31.00",
            "capacity": "11",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/options/{SHUTTLE_ID}"

    detail = client.get(f"/options/{SHUTTLE_ID}")
    assert "50m" in detail.text


def test_update_option_cannot_shrink_capacity_below_the_plan(
    client: TestClient,
) -> None:
    response = _post(
        client,
        f"/options/{SHUTTLE_ID}/edit",
        NEW_OPTION
        | {
            "type": "transfer",
            "provider": "Queenstown Snow Shuttle",
            "origin": "Queenstown Airport",
            "destination": "Queenstown Town Centre",
            "departure_time": "2027-07-10T14:20",
            "arrival_time": "2027-07-10T14:55",
            "price": "28.00",
            "capacity": "2",
        },
    )

    assert response.status_code == 200
    assert "to cover existing bookings" in response.text


def test_delete_confirmation_warns_when_trips_still_plan_it(
    client: TestClient,
) -> None:
    response = client.get(f"/options/{FLIGHT_ID}/delete")

    assert response.status_code == 200
    assert "1 trip(s) still plan this transport" in response.text


def test_delete_blocked_option_replays_the_conflict(client: TestClient) -> None:
    response = _post(client, f"/options/{FLIGHT_ID}/delete", {})

    assert response.status_code == 200
    assert "CONFLICT" in response.text


def test_delete_unused_option_returns_to_browse(client: TestClient) -> None:
    created = _post(client, "/options", NEW_OPTION | {"id": "transport_ui_disposable"})
    assert created.status_code == 303

    response = _post(client, "/options/transport_ui_disposable/delete", {})

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.get("/options/transport_ui_disposable").status_code == 200


# --------------------------------------------------------------------- compare


def test_compare_page_lists_selectable_options(client: TestClient) -> None:
    response = client.get("/compare")

    assert response.status_code == 200
    assert "Choose transport options" in response.text
    assert "up to 4 options" in response.text


def test_compare_renders_a_side_by_side_table(client: TestClient) -> None:
    response = client.get("/compare", params={"ids": [FLIGHT_ID, TOKYO_ID]})

    assert response.status_code == 200
    assert "Comparison" in response.text
    assert "Price per traveller" in response.text
    assert "Japan Airlines" in response.text
    assert "Qantas" in response.text


def test_compare_replays_the_selection_limit(client: TestClient) -> None:
    response = client.get(
        "/compare",
        params={
            "ids": [
                FLIGHT_ID,
                "transport_2026_qf436_syd_mel",
                "transport_2026_vline_mel_geelong",
                "transport_2026_skybus_mel_city",
                SHUTTLE_ID,
            ],
        },
    )

    assert response.status_code == 200
    assert "must not select more than 4 options" in response.text


def test_compare_keeps_checkboxes_ticked(client: TestClient) -> None:
    response = client.get("/compare", params={"ids": [SHUTTLE_ID]})

    assert f'value="{SHUTTLE_ID}"' in response.text
    assert "checked" in response.text


# ---------------------------------------------------------------- plan entries


def test_trip_transport_shows_the_composed_plan(client: TestClient) -> None:
    response = client.get(f"/trips/{SYDNEY_TRIP}/transport")

    assert response.status_code == 200
    assert f"Transport for {SYDNEY_TRIP}" in response.text
    assert "$789.00" in response.text
    assert "In the itinerary" in response.text


def test_trip_transport_is_empty_for_an_unplanned_trip(client: TestClient) -> None:
    response = client.get("/trips/trip_2030_unplanned_trip/transport")

    assert response.status_code == 200
    assert "No transport planned for this trip yet" in response.text


def test_new_entry_form_prefills_from_the_query(client: TestClient) -> None:
    response = client.get("/plan/new", params={"transport_id": SHUTTLE_ID})

    assert response.status_code == 200
    assert f'value="{SHUTTLE_ID}"' in response.text
    assert "No reservation is made" in response.text


def test_create_entry_redirects_to_the_trip_plan(client: TestClient) -> None:
    response = _post(client, "/plan", NEW_ENTRY)

    assert response.status_code == 303
    assert response.headers["location"] == f"/trips/{QUEENSTOWN_TRIP}/transport"

    plan = client.get(f"/trips/{QUEENSTOWN_TRIP}/transport")
    # 28.00 x 2 derived by the database, plus the seeded 3-traveller entry.
    assert "$56.00" in plan.text


def test_create_entry_replays_a_capacity_conflict(client: TestClient) -> None:
    response = _post(
        client,
        "/plan",
        NEW_ENTRY | {"traveller_count": "9", "booking_status": "confirmed"},
    )

    assert response.status_code == 200
    assert "exceeds remaining capacity" in response.text


def test_create_entry_replays_a_late_booking_date(client: TestClient) -> None:
    response = _post(client, "/plan", NEW_ENTRY | {"booking_date": "2027-07-11"})

    assert response.status_code == 200
    assert "must be on or before the transport departure date" in response.text


def test_create_entry_rejects_a_sold_out_option(client: TestClient) -> None:
    response = _post(
        client,
        "/plan",
        NEW_ENTRY
        | {
            "trip_id": "trip_2026_singapore_stopover",
            "transport_id": "transport_2026_sq232_syd_sin",
            "booking_date": "2026-08-01",
        },
    )

    assert response.status_code == 200
    assert "is not bookable while its availability_status" in response.text


def test_edit_entry_form_is_prefilled(client: TestClient) -> None:
    response = client.get(f"/plan/{BOOKED_ENTRY}/edit")

    assert response.status_code == 200
    assert f'value="{QUEENSTOWN_TRIP}"' in response.text
    assert 'value="3"' in response.text


def test_update_entry_redirects_to_the_trip_plan(client: TestClient) -> None:
    response = _post(
        client,
        f"/plan/{BOOKED_ENTRY}/edit",
        {
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": "4",
            "booking_date": "2027-05-02",
            "estimated_cost": "",
            "booking_status": "confirmed",
            "notes": "",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/trips/{QUEENSTOWN_TRIP}/transport"

    plan = client.get(f"/trips/{QUEENSTOWN_TRIP}/transport")
    assert "$112.00" in plan.text


def test_cancelling_an_entry_drops_it_from_the_total(client: TestClient) -> None:
    before = client.get(f"/trips/{QUEENSTOWN_TRIP}/transport")
    assert "$84.00" in before.text

    response = _post(
        client,
        f"/plan/{BOOKED_ENTRY}/edit",
        {
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": "3",
            "booking_date": "2027-05-02",
            "estimated_cost": "84.00",
            "booking_status": "cancelled",
            "notes": "",
        },
    )
    assert response.status_code == 303

    after = client.get(f"/trips/{QUEENSTOWN_TRIP}/transport")
    assert "$0.00" in after.text
    assert "Removed" in after.text


def test_delete_entry_confirmation_describes_the_entry(client: TestClient) -> None:
    response = client.get(f"/plan/{BOOKED_ENTRY}/delete")

    assert response.status_code == 200
    assert "3 traveller(s)" in response.text
    assert "$84.00" in response.text


def test_delete_entry_returns_to_the_trip_plan(client: TestClient) -> None:
    response = _post(client, f"/plan/{BOOKED_ENTRY}/delete", {})

    assert response.status_code == 303
    assert response.headers["location"] == f"/trips/{QUEENSTOWN_TRIP}/transport"

    plan = client.get(f"/trips/{QUEENSTOWN_TRIP}/transport")
    assert "No transport planned for this trip yet" in plan.text


def test_unknown_entry_renders_an_error_panel(client: TestClient) -> None:
    response = client.get("/plan/booking_missing_reference/edit")

    assert response.status_code == 200
    assert "Plan entry unavailable" in response.text


# ------------------------------------------------------------------- wording


def test_no_page_promises_a_real_reservation(client: TestClient) -> None:
    """The product plans transport; it never books it.

    Guards the wording across the screens a traveller actually sees, so the
    scope decision cannot quietly regress into booking language.
    """
    paths = [
        "/",
        "/compare",
        "/options/new",
        "/plan/new",
        f"/options/{SHUTTLE_ID}",
        f"/trips/{SYDNEY_TRIP}/transport",
    ]
    # Phrases that would promise a transaction. "payment" alone is not banned:
    # the pages say plainly that no payment is taken, and that wording must stay.
    banned = (
        "book now",
        "book this",
        "reserve now",
        "reserve this",
        "pay now",
        "proceed to payment",
        "checkout",
        "add to cart",
        "confirm booking",
    )

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        lowered = response.text.lower()
        for phrase in banned:
            assert phrase not in lowered, f"{phrase!r} appeared on {path}"


def test_the_shell_states_that_nothing_is_booked(client: TestClient) -> None:
    response = client.get("/")

    assert "does not book transport" in response.text


# ----------------------------------------------------------------------- htmx


def test_the_shell_is_htmx_boosted(client: TestClient) -> None:
    response = client.get("/")

    assert 'id="app-shell"' in response.text
    assert 'hx-boost="true"' in response.text
    assert 'hx-target="#app-shell"' in response.text


def test_pages_share_the_navigation_shell(client: TestClient) -> None:
    for path in ("/", "/compare", "/options/new", "/plan/new"):
        response = client.get(path)
        assert 'id="app-shell"' in response.text, path
        assert "Browse &amp; filter" in response.text, path


# ------------------------------------------------------------ swap regressions

HTMX_HEADERS = {"HX-Request": "true", "HX-Boosted": "true"}


def test_htmx_request_returns_only_the_shell(client: TestClient) -> None:
    """A boosted request must not answer with a whole document.

    The shell swaps itself with hx-swap="outerHTML", so a full page response
    nests a second <head> and site header inside it, and they accumulate with
    every button press.
    """
    response = client.get("/compare", headers=HTMX_HEADERS)

    assert response.status_code == 200
    assert "<!DOCTYPE" not in response.text
    assert "<head>" not in response.text
    assert "site-header" not in response.text
    assert 'id="app-shell"' in response.text


def test_plain_request_still_returns_a_full_page(client: TestClient) -> None:
    response = client.get("/compare")

    assert "<!DOCTYPE" in response.text
    assert response.text.count("site-header") >= 1
    assert 'id="app-shell"' in response.text


def test_no_screen_duplicates_the_site_header_over_htmx(
    client: TestClient,
) -> None:
    paths = [
        "/",
        "/compare",
        "/options/new",
        "/plan/new",
        f"/options/{SHUTTLE_ID}",
        f"/trips/{SYDNEY_TRIP}/transport",
    ]
    for path in paths:
        response = client.get(path, headers=HTMX_HEADERS)
        assert response.status_code == 200, path
        assert 'class="site-header"' not in response.text, path
        assert response.text.count('id="app-shell"') == 1, path


def test_table_action_cells_stay_real_table_cells(client: TestClient) -> None:
    """display:flex on a <td> drops it out of the table layout.

    The cell then stops lining up under its own column, which is most obvious
    in the comparison table where the Actions row has one cell per option.
    """
    for path in (
        "/",
        f"/options/{SHUTTLE_ID}",
        f"/trips/{SYDNEY_TRIP}/transport",
        f"/compare?ids={FLIGHT_ID}&ids={TOKYO_ID}",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert '<td class="actions-cell"' not in response.text, path


def test_compare_actions_row_has_one_cell_per_option(client: TestClient) -> None:
    response = client.get("/compare", params={"ids": [FLIGHT_ID, TOKYO_ID]})

    assert response.status_code == 200
    actions_row = response.text.split('<th scope="row">Actions</th>')[1]
    actions_row = actions_row.split("</tr>")[0]
    assert actions_row.count("<td>") == 2
    assert actions_row.count("Add to trip") == 2
    assert actions_row.count(">View<") == 2


# --------------------------------------------------------------- input controls


def test_trip_field_is_a_picker_when_student_1_is_reachable(
    client_with_trips: TestClient,
) -> None:
    response = client_with_trips.get("/plan/new")

    assert response.status_code == 200
    assert '<select id="trip_id" name="trip_id">' in response.text
    # Readable label, not a raw identifier.
    assert "Sydney Long Weekend" in response.text
    assert "Sydney, 2026-10-02 to 2026-10-05" in response.text
    assert "Queenstown Ski Escape" in response.text


def test_trip_picker_preselects_the_trip_from_the_query(
    client_with_trips: TestClient,
) -> None:
    response = client_with_trips.get("/plan/new", params={"trip_id": SYDNEY_TRIP})

    assert f'value="{SYDNEY_TRIP}" selected' in response.text


def test_trip_field_degrades_to_text_when_student_1_is_down(
    client: TestClient,
) -> None:
    """A dependency outage must not make the form unusable.

    The default fixture has Student 1 unreachable, so this is the degraded path.
    """
    response = client.get("/plan/new")

    assert response.status_code == 200
    assert '<select id="trip_id"' not in response.text
    assert '<input id="trip_id" name="trip_id" type="text"' in response.text
    assert "trips service is unavailable" in response.text


def test_transport_field_is_always_a_picker(client: TestClient) -> None:
    """Transport options are Student 3's own data, so the picker never degrades."""
    response = client.get("/plan/new")

    assert '<select id="transport_id" name="transport_id">' in response.text
    assert "Queenstown Airport to Queenstown Town Centre" in response.text
    assert "Queenstown Snow Shuttle" in response.text


def test_transport_picker_preselects_from_the_query(client: TestClient) -> None:
    response = client.get("/plan/new", params={"transport_id": SHUTTLE_ID})

    assert f'value="{SHUTTLE_ID}" selected' in response.text


def test_plan_form_uses_native_date_and_number_controls(
    client: TestClient,
) -> None:
    response = client.get("/plan/new")

    assert '<input id="booking_date" name="booking_date" type="date"' in response.text
    assert 'id="traveller_count"' in response.text
    assert 'type="number"' in response.text
    assert 'min="1"' in response.text


def test_option_form_uses_datetime_and_number_controls(client: TestClient) -> None:
    response = client.get("/options/new")

    assert 'name="departure_time" type="datetime-local"' in response.text
    assert 'name="arrival_time" type="datetime-local"' in response.text
    assert 'name="price"' in response.text
    assert 'step="0.01"' in response.text
    assert 'name="capacity"' in response.text


def test_option_form_offers_time_zones_as_a_picker(client: TestClient) -> None:
    """A raw offset in minutes is not something a user should have to work out."""
    response = client.get("/options/new")

    assert '<select id="departure_utc_offset"' in response.text
    assert '<select id="arrival_utc_offset"' in response.text
    assert "UTC+10:00" in response.text
    assert "UTC+05:30" in response.text
    assert "UTC-12:00" in response.text
    assert "Not specified" in response.text
    # The submitted value stays the minutes the API expects.
    assert 'value="600"' in response.text


def test_edit_option_form_preselects_the_stored_time_zones(
    client: TestClient,
) -> None:
    response = client.get("/options/transport_2027_jl772_syd_hnd/edit")

    assert response.status_code == 200
    assert 'value="660" selected' in response.text
    assert 'value="540" selected' in response.text


def test_browse_filters_use_native_controls(client: TestClient) -> None:
    response = client.get("/")

    assert 'id="min_price" name="min_price" type="number"' in response.text
    assert 'id="departure_from" name="departure_from" type="datetime-local"' in (
        response.text
    )


def test_picking_from_the_dropdowns_creates_a_plan_entry(
    client_with_trips: TestClient,
) -> None:
    """End to end with picker values, which are the plain identifiers."""
    response = _post(
        client_with_trips,
        "/plan",
        {
            "trip_id": QUEENSTOWN_TRIP,
            "transport_id": SHUTTLE_ID,
            "traveller_count": "2",
            "booking_date": "2027-05-03",
            "estimated_cost": "",
            "booking_status": "pending",
            "notes": "",
        },
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/trips/{QUEENSTOWN_TRIP}/transport"
