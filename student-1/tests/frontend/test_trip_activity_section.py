from __future__ import annotations

SYDNEY = "trip_2027_sydney_getaway"


def test_selected_activity_shows_schedule_and_enriched_details(client, backend_api):
    backend_api.pin_activity(
        SYDNEY,
        activity_id="activity_harbour_cruise",
        name="Harbour Cruise",
        date="2027-04-02",
        start_time="14:30",
        price="89.00",
        pricing_basis="PER_PERSON",
        duration_minutes=90,
    )

    response = client.get(f"/trips/{SYDNEY}")

    assert response.status_code == 200
    assert 'aria-labelledby="activities-heading"' in response.text
    assert "Harbour Cruise" in response.text
    assert "2027-04-02 at 14:30" in response.text
    assert "$89.00 per person" in response.text
    assert "90 minutes" in response.text


def test_unenriched_activity_falls_back_to_stored_selection(client, backend_api):
    backend_api.pin_activity(
        SYDNEY,
        activity_id="activity_unavailable",
        date="2027-04-03",
        start_time=None,
    )

    response = client.get(f"/trips/{SYDNEY}")

    assert response.status_code == 200
    assert "activity_unavailable" in response.text
    assert "2027-04-03" in response.text
    assert "Time not recorded" in response.text


def test_empty_activity_list_keeps_trip_page_available(client):
    response = client.get(f"/trips/{SYDNEY}")

    assert response.status_code == 200
    assert "No activities selected for this trip yet." in response.text
