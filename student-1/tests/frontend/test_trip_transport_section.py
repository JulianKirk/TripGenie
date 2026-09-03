from __future__ import annotations

SYDNEY = "trip_2027_sydney_getaway"


def test_selected_transport_shows_enriched_route_and_cost(client, backend_api):
    backend_api.pin_transport(
        SYDNEY,
        transport_id="transport_sydney_train",
        provider="Sydney Trains",
        type="train",
        origin="Central",
        destination="Circular Quay",
        departure_time="2027-04-01T10:00:00+11:00",
        arrival_time="2027-04-01T10:15:00+11:00",
        duration_minutes=15,
        price=5.20,
        pricing_basis="per_traveller",
        estimated_cost=10.40,
        plan_status="confirmed",
        notes="Quiet carriage requested.",
    )

    response = client.get(f"/trips/{SYDNEY}")

    assert response.status_code == 200
    assert 'aria-labelledby="transport-heading"' in response.text
    assert "Sydney Trains train" in response.text
    assert "Central to Circular Quay" in response.text
    assert "2027-04-01T10:00:00+11:00" in response.text
    assert "15 minutes" in response.text
    assert "$10.40 estimated total" in response.text
    assert "Confirmed" in response.text
    assert "Quiet carriage requested." in response.text


def test_unenriched_transport_falls_back_to_stored_selection(client, backend_api):
    backend_api.pin_transport(
        SYDNEY,
        transport_id="transport_unavailable",
        traveller_count=3,
    )

    response = client.get(f"/trips/{SYDNEY}")

    assert response.status_code == 200
    assert "transport_unavailable" in response.text
    assert "3 travellers" in response.text


def test_empty_transport_list_keeps_trip_page_available(client):
    response = client.get(f"/trips/{SYDNEY}")

    assert response.status_code == 200
    assert "No transport selected for this trip yet." in response.text
