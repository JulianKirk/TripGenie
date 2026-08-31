"""The public accommodation-pinning API, against the faked database service."""

from __future__ import annotations

from fastapi.testclient import TestClient

ACCOMMODATION_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000001"
SYDNEY = "trip_2027_sydney_getaway"
TOKYO = "trip_2027_tokyo_city_break"

TRIP_PAYLOAD = {
    "name": "Canberra Planning Sprint",
    "destination": "Canberra",
    "start_date": "2027-05-01",
    "end_date": "2027-05-04",
    "traveller_count": 2,
    "status": "planned",
}


def test_adding_an_accommodation_pins_it_to_the_trip_start_date(
    client: TestClient,
) -> None:
    """The accommodation service has no opinion about which day, and an item
    must fall inside the trip window, so the start date is the safe choice."""
    response = client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "trip_id": SYDNEY,
        "accommodation_id": ACCOMMODATION_ID,
        "date": "2027-04-01",
    }


def test_adding_the_same_accommodation_twice_stays_a_200(
    client: TestClient,
) -> None:
    first = client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")
    second = client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    assert first.status_code == second.status_code == 200
    listed = client.get(f"/api/trips/{SYDNEY}/accommodations").json()["data"]
    assert len(listed) == 1


def test_accommodations_appear_on_the_trip_detail(client: TestClient) -> None:
    client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    detail = client.get(f"/api/trips/{SYDNEY}")

    assert detail.status_code == 200
    assert detail.json()["data"]["accommodations"] == [
        {
            "trip_id": SYDNEY,
            "accommodation_id": ACCOMMODATION_ID,
            "date": "2027-04-01",
        },
    ]


def test_a_new_trip_starts_with_no_accommodations(client: TestClient) -> None:
    created = client.post("/api/trips", json=TRIP_PAYLOAD)

    assert created.status_code == 201
    assert created.json()["data"]["accommodations"] == []


def test_reverse_lookup_lists_every_trip_holding_the_accommodation(
    client: TestClient,
) -> None:
    client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")
    client.put(f"/api/trips/{TOKYO}/accommodations/{ACCOMMODATION_ID}")

    response = client.get(f"/api/accommodations/{ACCOMMODATION_ID}/trips")

    assert response.status_code == 200
    assert [trip["id"] for trip in response.json()["data"]] == [SYDNEY, TOKYO]


def test_removing_an_accommodation_drops_it_from_both_directions(
    client: TestClient,
) -> None:
    client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    removed = client.delete(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    assert removed.status_code == 200
    assert removed.json()["data"] == {"id": ACCOMMODATION_ID, "deleted": True}
    assert client.get(f"/api/trips/{SYDNEY}/accommodations").json()["data"] == []
    reverse = client.get(f"/api/accommodations/{ACCOMMODATION_ID}/trips")
    assert reverse.json()["data"] == []


def test_removing_an_accommodation_that_is_not_pinned_is_a_404(
    client: TestClient,
) -> None:
    response = client.delete(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_unknown_trip_is_a_404(client: TestClient) -> None:
    response = client.put(
        f"/api/trips/trip_missing_00/accommodations/{ACCOMMODATION_ID}",
    )

    assert response.status_code == 404


def test_a_malformed_accommodation_id_is_rejected_before_the_database(
    client: TestClient,
    database_api,
) -> None:
    """The id comes from another service, so it is validated at the boundary
    rather than concatenated into a path."""
    response = client.put(f"/api/trips/{SYDNEY}/accommodations/not a valid id")

    assert response.status_code == 422
    assert database_api.trip_accommodations == {}
