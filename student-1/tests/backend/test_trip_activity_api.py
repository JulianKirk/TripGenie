"""Public trip/activity association API, against faked dependencies."""

from fastapi.testclient import TestClient

ACTIVITY_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
SYDNEY = "trip_2027_sydney_getaway"
TOKYO = "trip_2027_tokyo_city_break"


def test_bodyless_put_adds_activity_on_trip_start(client: TestClient) -> None:
    response = client.put(f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "trip_id": SYDNEY,
        "activity_id": ACTIVITY_ID,
        "date": "2027-04-01",
        "start_time": None,
    }


def test_put_stores_and_replaces_activity_schedule(client: TestClient) -> None:
    client.put(
        f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}",
        json={"date": "2027-04-02", "start_time": "10:15"},
    )
    response = client.put(
        f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}",
        json={"date": "2027-04-03", "start_time": "14:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["date"] == "2027-04-03"
    assert client.get(f"/api/trips/{SYDNEY}/activities").json()["data"] == [
        response.json()["data"]
    ]


def test_activity_date_must_be_inside_trip(client: TestClient) -> None:
    response = client.put(
        f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}",
        json={"date": "2027-04-09"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "date"


def test_reverse_lookup_and_delete(client: TestClient) -> None:
    client.put(f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}")
    client.put(f"/api/trips/{TOKYO}/activities/{ACTIVITY_ID}")

    reverse = client.get(f"/api/activities/{ACTIVITY_ID}/trips")
    assert [trip["id"] for trip in reverse.json()["data"]] == [SYDNEY, TOKYO]

    removed = client.delete(f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}")
    assert removed.status_code == 200
    assert removed.json()["data"] == {"id": ACTIVITY_ID, "deleted": True}
    assert client.get(f"/api/trips/{SYDNEY}/activities").json()["data"] == []


def test_trip_detail_enriches_activity_from_student_4(
    client: TestClient,
    activity_api,
) -> None:
    activity_api.records[ACTIVITY_ID] = {
        "id": ACTIVITY_ID,
        "name": "Sydney Harbour Kayak",
        "price": "89.50",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
    }
    client.put(
        f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}",
        json={"date": "2027-04-02", "start_time": "09:30"},
    )

    response = client.get(f"/api/trips/{SYDNEY}")

    assert response.status_code == 200
    assert response.json()["data"]["activities"] == [
        {
            "trip_id": SYDNEY,
            "activity_id": ACTIVITY_ID,
            "date": "2027-04-02",
            "start_time": "09:30",
            "name": "Sydney Harbour Kayak",
            "price": "89.50",
            "pricing_basis": "PER_PERSON",
            "duration_minutes": 120,
        }
    ]


def test_malformed_or_missing_student_4_activity_does_not_hide_trip(
    client: TestClient,
    activity_api,
) -> None:
    activity_api.records[ACTIVITY_ID] = {
        "id": ACTIVITY_ID,
        "name": "Bad price",
        "price": "free",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 30,
    }
    client.put(f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}")

    response = client.get(f"/api/trips/{SYDNEY}")

    assert response.status_code == 200
    activity = response.json()["data"]["activities"][0]
    assert activity["activity_id"] == ACTIVITY_ID
    assert activity["name"] is None
    assert activity["price"] is None


def test_new_trip_starts_with_no_activities(client: TestClient) -> None:
    response = client.post(
        "/api/trips",
        json={
            "name": "Canberra Planning Sprint",
            "destination": "Canberra",
            "start_date": "2027-05-01",
            "end_date": "2027-05-04",
            "traveller_count": 2,
            "status": "planned",
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["activities"] == []


def test_public_trip_update_cannot_exclude_a_selected_activity(
    client: TestClient,
    database_api,
) -> None:
    client.put(
        f"/api/trips/{SYDNEY}/activities/{ACTIVITY_ID}",
        json={"date": "2027-04-03"},
    )

    response = client.patch(f"/api/trips/{SYDNEY}", json={"end_date": "2027-04-02"})

    assert response.status_code == 422
    assert database_api.trip_update_calls == 0
