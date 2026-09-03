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
        "check_in_time": None,
        "check_out": None,
        "check_out_time": None,
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
            "check_in_time": None,
            "check_out": None,
            "check_out_time": None,
            # Student 2 does not know this id in the fake, so the trip page
            # gets the stay without a label rather than an error.
            "name": None,
            "price_per_night": None,
            "total_price": None,
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


def test_a_chosen_stay_window_is_stored(client: TestClient) -> None:
    """The point of the body: the caller says when, instead of the service
    guessing the trip's first day."""
    response = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-04-02", "check_out": "2027-04-03"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["date"] == "2027-04-02"
    assert response.json()["data"]["check_out"] == "2027-04-03"


def test_a_stay_starting_before_the_trip_is_rejected(client: TestClient) -> None:
    response = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-03-30"},
    )

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert [detail["field"] for detail in details] == ["date"]


def test_a_stay_ending_after_the_trip_is_rejected(client: TestClient) -> None:
    response = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-04-02", "check_out": "2027-04-09"},
    )

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert [detail["field"] for detail in details] == ["check_out"]


def test_a_checkout_before_the_checkin_is_rejected(client: TestClient) -> None:
    response = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-04-03", "check_out": "2027-04-01"},
    )

    assert response.status_code == 422


def test_re_pinning_moves_the_stay(client: TestClient) -> None:
    """PUT replaces the pin. A user correcting their dates must see the
    correction stick, not silently keep the first answer."""
    client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-04-01", "check_out": "2027-04-02"},
    )
    second = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-04-02", "check_out": "2027-04-03"},
    )

    assert second.json()["data"]["date"] == "2027-04-02"
    listed = client.get(f"/api/trips/{SYDNEY}/accommodations").json()["data"]
    assert len(listed) == 1


def test_the_stay_carries_arrival_and_departure_times(client: TestClient) -> None:
    response = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={
            "date": "2027-04-01",
            "check_in_time": "15:00",
            "check_out": "2027-04-03",
            "check_out_time": "10:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["check_in_time"] == "15:00"
    assert response.json()["data"]["check_out_time"] == "10:00"


def test_a_same_day_stay_must_check_out_after_it_checks_in(
    client: TestClient,
) -> None:
    """Only the times separate arrival from departure on a day-use booking."""
    response = client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={
            "date": "2027-04-02",
            "check_in_time": "14:00",
            "check_out": "2027-04-02",
            "check_out_time": "09:00",
        },
    )

    assert response.status_code == 422
    body = response.json()["error"]
    # Its own message: the dates are fine, so pointing at them would send the
    # user to correct the one thing that is not wrong.
    assert "check out after it checks in" in body["message"]
    assert body["details"][0]["field"] == "check_out_time"


def test_the_trip_detail_labels_and_prices_the_stay(
    client: TestClient,
    accommodation_api,
) -> None:
    """A trip stores an id; the page needs a name and what the stay costs, and
    both come from student 2."""
    accommodation_api.records[ACCOMMODATION_ID] = {
        "id": ACCOMMODATION_ID,
        "name": "Harbour View Hotel",
        "price_per_night": 220.0,
    }
    client.put(
        f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-04-01", "check_out": "2027-04-03"},
    )

    stay = client.get(f"/api/trips/{SYDNEY}").json()["data"]["accommodations"][0]

    assert stay["name"] == "Harbour View Hotel"
    assert stay["price_per_night"] == 220.0
    # Two nights, not three days.
    assert stay["total_price"] == 440.0


def test_an_unreachable_accommodation_service_still_returns_the_trip(
    client: TestClient,
    accommodation_api,
) -> None:
    """Losing a name must not cost the trip. The stay renders unlabelled."""
    client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    response = client.get(f"/api/trips/{SYDNEY}")

    assert response.status_code == 200
    stay = response.json()["data"]["accommodations"][0]
    assert stay["name"] is None
    assert stay["date"] == "2027-04-01"
    assert accommodation_api.calls == [ACCOMMODATION_ID]


def test_a_stay_with_no_departure_has_no_total(
    client: TestClient,
    accommodation_api,
) -> None:
    accommodation_api.records[ACCOMMODATION_ID] = {
        "name": "Harbour View Hotel",
        "price_per_night": 220.0,
    }
    client.put(f"/api/trips/{SYDNEY}/accommodations/{ACCOMMODATION_ID}")

    stay = client.get(f"/api/trips/{SYDNEY}").json()["data"]["accommodations"][0]

    assert stay["price_per_night"] == 220.0
    assert stay["total_price"] is None


class TestValidationErrorContract:
    """400 and 422 are different conditions, not two spellings of one.

    Documented in backend/README.md. Asserted here because the accommodation
    routes inherit the contract rather than declaring it, so a change to the
    shared dependency would otherwise move their behaviour silently.
    """

    def test_an_unknown_query_param_is_a_400(self, client: TestClient) -> None:
        response = client.get(f"/api/trips/{SYDNEY}/accommodations?bogus=1")

        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "BAD_REQUEST"
        # The offending name is named, so a typo is diagnosable.
        assert body["details"] == [{"field": "bogus", "issue": "is not supported"}]

    def test_a_malformed_path_id_is_a_422(self, client: TestClient) -> None:
        response = client.get("/api/trips/bad!id/accommodations")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_a_well_formed_unknown_id_is_a_404(self, client: TestClient) -> None:
        response = client.get("/api/trips/trip_not_here/accommodations")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_every_error_uses_the_same_envelope(self, client: TestClient) -> None:
        """Different statuses, one shape -- that is what makes the split
        navigable for a caller."""
        for path in (
            f"/api/trips/{SYDNEY}/accommodations?bogus=1",
            "/api/trips/bad!id/accommodations",
            "/api/trips/trip_not_here/accommodations",
        ):
            body = client.get(path).json()
            assert set(body) == {"error"}
            assert set(body["error"]) >= {"code", "message", "details"}
