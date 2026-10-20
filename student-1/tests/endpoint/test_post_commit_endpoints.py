"""Post-commit endpoint tests against the live Student 1 Compose stack.

student-1-ci.yml's compose job runs these over HTTP once the stack is ready.
They skip when nothing answers at the base URL, so a bare `pytest` run without
the stack stays green; testpaths in pyproject.toml leaves this directory out.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import httpx
import pytest

BASE_URL = os.environ.get("STUDENT1_ENDPOINT_BASE_URL", "http://127.0.0.1:18001")


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"{BASE_URL}/api", timeout=10) as http:
        try:
            http.get(f"{BASE_URL}/health")
        except httpx.TransportError:
            pytest.skip(f"Student 1 backend is not reachable at {BASE_URL}")
        yield http


def trip_payload(**overrides: object) -> dict[str, object]:
    return {
        "id": f"trip_ci_{uuid.uuid4().hex[:12]}",
        "name": "CI Endpoint Trip",
        "destination": "Sydney",
        "start_date": "2027-03-01",
        "end_date": "2027-03-03",
        "traveller_count": 2,
        "status": "planned",
    } | overrides


@pytest.fixture
def trip(client: httpx.Client) -> Iterator[dict[str, object]]:
    response = client.post("/trips", json=trip_payload())
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    yield created
    # Deleting the trip cascades to its itinerary items, so reruns start clean.
    client.delete(f"/trips/{created['id']}")


def item_payload(**overrides: object) -> dict[str, object]:
    return {
        "id": f"item_ci_{uuid.uuid4().hex[:12]}",
        "date": "2027-03-02",
        "start_time": "09:00",
        "end_time": "10:30",
        "title": "Harbour walk",
        "category": "activity",
    } | overrides


def assert_validation_error(response: httpx.Response, field: str) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert field in {detail["field"] for detail in error["details"]}


# Endpoint 1: POST /api/trips


def test_create_trip_returns_201_with_persisted_fields(client, trip):
    sent = trip_payload(id=trip["id"])
    assert {key: trip[key] for key in sent} == sent
    assert [day["date"] for day in trip["days"]] == [
        "2027-03-01",
        "2027-03-02",
        "2027-03-03",
    ]

    fetched = client.get(f"/trips/{trip['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["name"] == sent["name"]


def test_created_trip_is_listed(client, trip):
    response = client.get("/trips")
    assert response.status_code == 200
    assert trip["id"] in {listed["id"] for listed in response.json()["data"]}


def test_create_trip_rejects_end_before_start(client):
    payload = trip_payload(start_date="2027-03-05", end_date="2027-03-01")
    assert_validation_error(client.post("/trips", json=payload), "start_date")
    assert client.get(f"/trips/{payload['id']}").status_code == 404


def test_create_trip_rejects_missing_name(client):
    payload = trip_payload()
    del payload["name"]
    assert_validation_error(client.post("/trips", json=payload), "name")
    assert client.get(f"/trips/{payload['id']}").status_code == 404


# Endpoint 2: POST /api/trips/{trip_id}/itinerary-items


def test_create_item_within_trip_returns_201_and_shows_on_day(client, trip):
    sent = item_payload()
    response = client.post(f"/trips/{trip['id']}/itinerary-items", json=sent)
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    assert created["trip_id"] == trip["id"]
    assert {key: created[key] for key in sent} == sent

    day = client.get(f"/trips/{trip['id']}/days/{sent['date']}")
    assert day.status_code == 200
    assert sent["id"] in {item["id"] for item in day.json()["data"]["items"]}


def test_create_item_for_unknown_trip_returns_404(client):
    unknown = f"trip_ci_missing_{uuid.uuid4().hex[:12]}"
    response = client.post(f"/trips/{unknown}/itinerary-items", json=item_payload())
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_create_item_outside_trip_dates_is_rejected(client, trip):
    sent = item_payload(date="2027-03-10")
    response = client.post(f"/trips/{trip['id']}/itinerary-items", json=sent)
    assert_validation_error(response, "date")

    items = client.get(f"/trips/{trip['id']}/itinerary-items")
    assert items.status_code == 200
    assert items.json()["data"] == []
