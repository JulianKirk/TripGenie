"""The associative entity between trips and accommodations.

A trip holds many accommodations and an accommodation sits on many trips, so
these cover both directions plus the idempotence the picker relies on.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from database_service.config import Settings
from database_service.repository import DatabaseService
from fastapi.testclient import TestClient

ACCOMMODATION_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000001"
OTHER_ACCOMMODATION_ID = "0f2b1c4e-aaaa-bbbb-cccc-000000000002"


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


def test_accommodation_is_added_listed_and_removed(
    client: TestClient,
    trip_id: str,
) -> None:
    added = client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-01"},
    )
    assert added.status_code == 200
    assert added.json()["data"] == {
        "trip_id": trip_id,
        "accommodation_id": ACCOMMODATION_ID,
        "date": "2027-05-01",
        "check_in_time": None,
        "check_out": None,
        "check_out_time": None,
    }

    listed = client.get(f"/internal/trips/{trip_id}/accommodations")
    assert listed.status_code == 200
    assert [record["accommodation_id"] for record in listed.json()["data"]] == [
        ACCOMMODATION_ID
    ]

    removed = client.delete(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
    )
    assert removed.status_code == 200
    assert removed.json()["data"] == {"id": ACCOMMODATION_ID, "deleted": True}
    assert client.get(f"/internal/trips/{trip_id}/accommodations").json()["data"] == []


def test_adding_the_same_accommodation_twice_is_not_a_conflict(
    client: TestClient,
    trip_id: str,
) -> None:
    """Re-pinning must not fail, and must not create a second row.

    It *does* move the dates. The user picks the stay now rather than the
    service inventing it, so a second PUT is someone correcting what they
    entered -- keeping the first answer would silently discard an edit they
    watched themselves make.
    """
    first = client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-01"},
    )
    second = client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-03", "check_out": "2027-05-06"},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["data"]["date"] == "2027-05-03"
    assert second.json()["data"]["check_out"] == "2027-05-06"
    listed = client.get(f"/internal/trips/{trip_id}/accommodations").json()["data"]
    assert len(listed) == 1


def test_removing_an_accommodation_that_was_never_added_is_a_404(
    client: TestClient,
    trip_id: str,
) -> None:
    response = client.delete(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unknown_trip_is_a_404_on_every_route(client: TestClient) -> None:
    missing = "trip_does_not_exist"
    assert client.get(f"/internal/trips/{missing}/accommodations").status_code == 404
    assert (
        client.put(
            f"/internal/trips/{missing}/accommodations/{ACCOMMODATION_ID}",
            json={"date": "2027-05-01"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/internal/trips/{missing}/accommodations/{ACCOMMODATION_ID}",
        ).status_code
        == 404
    )


def test_reverse_lookup_returns_every_trip_holding_the_accommodation(
    client: TestClient,
) -> None:
    """The query the accommodation service's picker asks: which trips are
    already ticked for this one accommodation?"""
    earlier = client.post(
        "/internal/trips",
        json=create_trip_payload(
            name="Alpine Week", start_date="2027-04-01", end_date="2027-04-05"
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

    for trip in (earlier, later):
        client.put(
            f"/internal/trips/{trip}/accommodations/{ACCOMMODATION_ID}",
            json={"date": "2027-04-01"},
        )
    client.put(
        f"/internal/trips/{unrelated}/accommodations/{OTHER_ACCOMMODATION_ID}",
        json={"date": "2027-05-01"},
    )

    response = client.get(f"/internal/accommodations/{ACCOMMODATION_ID}/trips")
    assert response.status_code == 200
    # Ordered the same way the trip list is, so the picker reads in one order.
    assert [trip["id"] for trip in response.json()["data"]] == [earlier, later]


def test_deleting_a_trip_removes_its_accommodation_links(
    client: TestClient,
    trip_id: str,
) -> None:
    client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-01"},
    )
    assert client.delete(f"/internal/trips/{trip_id}").status_code == 200

    response = client.get(f"/internal/accommodations/{ACCOMMODATION_ID}/trips")
    assert response.json()["data"] == []


def test_a_stay_window_is_stored_and_returned(
    client: TestClient,
    trip_id: str,
) -> None:
    added = client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-01", "check_out": "2027-05-03"},
    )

    assert added.status_code == 200
    assert added.json()["data"]["date"] == "2027-05-01"
    assert added.json()["data"]["check_out"] == "2027-05-03"


def test_a_checkout_before_the_checkin_is_rejected(
    client: TestClient,
    trip_id: str,
) -> None:
    """The table cannot carry this as a CHECK, so the model is the only thing
    standing between a caller and a stay that ends before it starts."""
    response = client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-03", "check_out": "2027-05-01"},
    )

    assert response.status_code == 422


def test_a_same_day_stay_is_allowed(client: TestClient, trip_id: str) -> None:
    """A day-use room is a real booking; only going backwards is wrong."""
    response = client.put(
        f"/internal/trips/{trip_id}/accommodations/{ACCOMMODATION_ID}",
        json={"date": "2027-05-02", "check_out": "2027-05-02"},
    )

    assert response.status_code == 200


def test_a_database_written_before_check_out_existed_gains_the_column(
    database_path: Path,
    settings: Settings,
) -> None:
    """CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    so without the ALTER every deployed volume would keep the old shape and
    every write would fail. Builds the pre-change table by hand and opens the
    service on top of it."""
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE trips (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, destination TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            traveller_count INTEGER NOT NULL, status TEXT NOT NULL, notes TEXT
        );
        CREATE TABLE trip_accommodations (
            trip_id TEXT NOT NULL, accommodation_id TEXT NOT NULL,
            date TEXT NOT NULL, PRIMARY KEY (trip_id, accommodation_id)
        );
        INSERT INTO trips VALUES
            ('trip_legacy', 'Old', 'Perth', '2027-05-01', '2027-05-04', 2,
             'planned', NULL);
        INSERT INTO trip_accommodations VALUES
            ('trip_legacy', 'acc_legacy', '2027-05-02');
        """,
    )
    connection.commit()
    connection.close()

    # initialize() is what the app calls on boot; the ALTER rides along with
    # the CREATE TABLEs there.
    service = DatabaseService(settings)
    service.initialize()
    listed = service.list_trip_accommodations("trip_legacy")

    # The row that predates the column survives, reading as "no departure".
    assert listed == [
        {
            "trip_id": "trip_legacy",
            "accommodation_id": "acc_legacy",
            "date": "2027-05-02",
            "check_in_time": None,
            "check_out": None,
            "check_out_time": None,
        },
    ]
