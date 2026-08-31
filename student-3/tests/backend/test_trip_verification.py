"""The opt-in trip existence check against Student 1's trips API.

Student 1 owns trips, so this service can only ask. The check is deliberately
forgiving: only a definitive "no" blocks a write, because a transport plan is
still useful when the trips service is down.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

ENTRIES_PATH = "/api/transport-bookings"
SHUTTLE_ID = "transport_2027_zqn_snow_shuttle"
KNOWN_TRIP = "trip_2027_queenstown_ski_escape"
UNKNOWN_TRIP = "trip_2030_never_created"

NEW_ENTRY: dict[str, Any] = {
    "trip_id": KNOWN_TRIP,
    "transport_id": SHUTTLE_ID,
    "traveller_count": 1,
    "booking_date": "2027-05-03",
    "booking_status": "pending",
}


def _build_client(
    database_transport: httpx.MockTransport,
    trips_transport: httpx.MockTransport,
    *,
    verify: bool,
) -> Iterator[TestClient]:
    settings = Settings(
        database_api_base_url="http://student-3-database:8004",
        verify_trip_exists=verify,
    )
    app = create_app(
        settings,
        transport=database_transport,
        trips_transport=trips_transport,
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def verifying_client(
    database_transport: httpx.MockTransport,
    known_trips_transport: httpx.MockTransport,
) -> Iterator[TestClient]:
    yield from _build_client(
        database_transport,
        known_trips_transport,
        verify=True,
    )


@pytest.fixture
def degraded_client(
    database_transport: httpx.MockTransport,
    unreachable_trips_transport: httpx.MockTransport,
) -> Iterator[TestClient]:
    yield from _build_client(
        database_transport,
        unreachable_trips_transport,
        verify=True,
    )


@pytest.fixture
def unverified_client(
    database_transport: httpx.MockTransport,
    known_trips_transport: httpx.MockTransport,
) -> Iterator[TestClient]:
    yield from _build_client(
        database_transport,
        known_trips_transport,
        verify=False,
    )


def test_entry_for_a_known_trip_is_accepted(verifying_client: TestClient) -> None:
    response = verifying_client.post(ENTRIES_PATH, json=NEW_ENTRY)

    assert response.status_code == 201, response.text


def test_entry_for_an_unknown_trip_is_rejected(verifying_client: TestClient) -> None:
    response = verifying_client.post(
        ENTRIES_PATH,
        json=NEW_ENTRY | {"trip_id": UNKNOWN_TRIP},
    )

    assert response.status_code == 422
    detail = response.json()["error"]["details"][0]
    assert detail["field"] == "trip_id"
    assert UNKNOWN_TRIP in detail["issue"]


def test_an_unreachable_trips_service_does_not_block_planning(
    degraded_client: TestClient,
) -> None:
    response = degraded_client.post(
        ENTRIES_PATH,
        json=NEW_ENTRY | {"trip_id": UNKNOWN_TRIP},
    )

    assert response.status_code == 201, response.text


def test_verification_is_off_by_default(unverified_client: TestClient) -> None:
    response = unverified_client.post(
        ENTRIES_PATH,
        json=NEW_ENTRY | {"trip_id": UNKNOWN_TRIP},
    )

    assert response.status_code == 201, response.text


def test_moving_an_entry_to_an_unknown_trip_is_rejected(
    verifying_client: TestClient,
) -> None:
    response = verifying_client.patch(
        f"{ENTRIES_PATH}/booking_2027_queenstown_transfer",
        json={"trip_id": UNKNOWN_TRIP},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "trip_id"


def test_editing_other_fields_skips_the_trip_lookup(
    degraded_client: TestClient,
) -> None:
    response = degraded_client.patch(
        f"{ENTRIES_PATH}/booking_2027_queenstown_transfer",
        json={"notes": "Ski carriage confirmed with the operator."},
    )

    assert response.status_code == 200
    assert _notes(response) == "Ski carriage confirmed with the operator."


def _notes(response) -> str | None:
    return response.json()["data"]["notes"]
