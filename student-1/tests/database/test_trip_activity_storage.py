"""The associative entity between trips and Student 4 activities."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ACTIVITY_ID = "5ee3fe1f-62e8-4b1a-bfca-f283781c24fd"
OTHER_ACTIVITY_ID = "975b8300-d47e-4c7f-826d-06f6b40404f2"


def create_trip_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Canberra Planning Sprint",
        "destination": "Canberra",
        "start_date": "2027-05-01",
        "end_date": "2027-05-04",
        "traveller_count": 2,
        "status": "planned",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def trip_id(client: TestClient) -> str:
    response = client.post("/internal/trips", json=create_trip_payload())
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


def test_activity_is_added_listed_and_removed(
    client: TestClient,
    trip_id: str,
) -> None:
    path = f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}"
    added = client.put(path, json={"date": "2027-05-02", "start_time": "09:30"})

    assert added.status_code == 200
    assert added.json()["data"] == {
        "trip_id": trip_id,
        "activity_id": ACTIVITY_ID,
        "date": "2027-05-02",
        "start_time": "09:30",
    }
    listed = client.get(f"/internal/trips/{trip_id}/activities")
    assert listed.status_code == 200
    assert listed.json()["data"] == [added.json()["data"]]

    removed = client.delete(path)
    assert removed.status_code == 200
    assert removed.json()["data"] == {"id": ACTIVITY_ID, "deleted": True}
    assert client.get(f"/internal/trips/{trip_id}/activities").json()["data"] == []


def test_put_replaces_the_same_activity_association(
    client: TestClient,
    trip_id: str,
) -> None:
    path = f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}"
    first = client.put(path, json={"date": "2027-05-01"})
    second = client.put(
        path,
        json={"date": "2027-05-03", "start_time": "14:15"},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["data"]["date"] == "2027-05-03"
    assert second.json()["data"]["start_time"] == "14:15"
    assert len(client.get(f"/internal/trips/{trip_id}/activities").json()["data"]) == 1


def test_reverse_lookup_returns_only_trips_holding_the_activity(
    client: TestClient,
) -> None:
    earlier = client.post(
        "/internal/trips",
        json=create_trip_payload(
            name="Alpine Week",
            start_date="2027-04-01",
            end_date="2027-04-05",
        ),
    ).json()["data"]["id"]
    later = client.post(
        "/internal/trips",
        json=create_trip_payload(name="Coast Run"),
    ).json()["data"]["id"]
    unrelated = client.post(
        "/internal/trips",
        json=create_trip_payload(name="Desert Drive"),
    ).json()["data"]["id"]

    client.put(
        f"/internal/trips/{earlier}/activities/{ACTIVITY_ID}",
        json={"date": "2027-04-01"},
    )
    client.put(
        f"/internal/trips/{later}/activities/{ACTIVITY_ID}",
        json={"date": "2027-05-01"},
    )
    client.put(
        f"/internal/trips/{unrelated}/activities/{OTHER_ACTIVITY_ID}",
        json={"date": "2027-05-01"},
    )

    response = client.get(f"/internal/activities/{ACTIVITY_ID}/trips")
    assert response.status_code == 200
    assert [trip["id"] for trip in response.json()["data"]] == [earlier, later]


def test_deleting_a_trip_cascades_its_activity_links(
    client: TestClient,
    trip_id: str,
) -> None:
    client.put(
        f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}",
        json={"date": "2027-05-01"},
    )
    assert client.delete(f"/internal/trips/{trip_id}").status_code == 200
    response = client.get(f"/internal/activities/{ACTIVITY_ID}/trips")
    assert response.json()["data"] == []


def test_unknown_trip_is_404_for_every_trip_activity_route(
    client: TestClient,
) -> None:
    missing = "trip_does_not_exist"
    assert client.get(f"/internal/trips/{missing}/activities").status_code == 404
    assert (
        client.put(
            f"/internal/trips/{missing}/activities/{ACTIVITY_ID}",
            json={"date": "2027-05-01"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/internal/trips/{missing}/activities/{ACTIVITY_ID}",
        ).status_code
        == 404
    )


def test_removing_a_missing_activity_selection_is_404(
    client: TestClient,
    trip_id: str,
) -> None:
    response = client.delete(
        f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}",
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("path_id", "body"),
    [
        ("not a valid id", {"date": "2027-05-01"}),
        (ACTIVITY_ID, {}),
        (ACTIVITY_ID, {"date": "not-a-date"}),
        (ACTIVITY_ID, {"date": "2027-05-01", "start_time": "25:00"}),
    ],
)
def test_invalid_activity_selection_is_422(
    client: TestClient,
    trip_id: str,
    path_id: str,
    body: dict[str, object],
) -> None:
    response = client.put(
        f"/internal/trips/{trip_id}/activities/{path_id}",
        json=body,
    )
    assert response.status_code == 422


def test_activity_list_order_is_date_then_identifier(
    client: TestClient,
    trip_id: str,
) -> None:
    client.put(
        f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}",
        json={"date": "2027-05-03"},
    )
    client.put(
        f"/internal/trips/{trip_id}/activities/{OTHER_ACTIVITY_ID}",
        json={"date": "2027-05-01"},
    )
    records = client.get(f"/internal/trips/{trip_id}/activities").json()["data"]
    assert [record["activity_id"] for record in records] == [
        OTHER_ACTIVITY_ID,
        ACTIVITY_ID,
    ]


def test_activity_date_outside_trip_is_rejected_by_database_boundary(
    client: TestClient,
    trip_id: str,
) -> None:
    response = client.put(
        f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}",
        json={"date": "2027-05-09"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "date"
    assert client.get(f"/internal/trips/{trip_id}/activities").json()["data"] == []


def test_trip_window_cannot_exclude_a_selected_activity(
    client: TestClient,
    trip_id: str,
) -> None:
    client.put(
        f"/internal/trips/{trip_id}/activities/{ACTIVITY_ID}",
        json={"date": "2027-05-04"},
    )

    response = client.patch(
        f"/internal/trips/{trip_id}", json={"end_date": "2027-05-03"}
    )

    assert response.status_code == 422
    assert "activity dates" in response.json()["error"]["details"][0]["issue"]
