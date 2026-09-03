from __future__ import annotations

import json
from copy import deepcopy

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, DETAIL, TRIP_ID, FakeBackend


def frontend(backend: FakeBackend) -> TestClient:
    return TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    )


def test_active_activity_offers_add_to_itinerary(backend: FakeBackend) -> None:
    text = frontend(backend).get(f"/activity/{ACTIVITY_ID}").text

    assert "Add to itinerary" in text
    assert f'hx-get="/activity/{ACTIVITY_ID}/itineraries"' in text
    assert 'hx-target="#itinerary-picker"' in text


def test_inactive_activity_does_not_offer_new_itinerary_selection(
    backend: FakeBackend,
) -> None:
    inactive = deepcopy(DETAIL)
    inactive["is_active"] = False
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=inactive
    )

    text = frontend(backend).get(f"/activity/{ACTIVITY_ID}").text

    assert "This activity is inactive" in text
    assert "Add to itinerary" not in text
    assert "Manage itinerary" in text


def test_inactive_selected_activity_remains_visible_and_removable(
    backend: FakeBackend,
) -> None:
    inactive = deepcopy(DETAIL)
    inactive["is_active"] = False
    selected = {
        "itineraries": [
            {
                "itinerary_id": TRIP_ID,
                "name": "Sydney Getaway",
                "selected": True,
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
                "date": "2027-04-02",
            }
        ]
    }
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=inactive
    )
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}/itineraries")] = httpx.Response(
        200, json=selected
    )

    text = frontend(backend).get(f"/activity/{ACTIVITY_ID}/itineraries").text

    assert "Added to this itinerary" in text
    assert "Remove" in text
    assert "Update" in text


def test_inactive_activity_does_not_offer_add_for_unselected_trip(
    backend: FakeBackend,
) -> None:
    inactive = deepcopy(DETAIL)
    inactive["is_active"] = False
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=inactive
    )

    text = frontend(backend).get(f"/activity/{ACTIVITY_ID}/itineraries").text

    assert "This activity must be active before it can be added" in text
    assert ">Add<" not in text


def test_inactive_activity_cannot_be_added_through_direct_post(
    backend: FakeBackend,
) -> None:
    inactive = deepcopy(DETAIL)
    inactive["is_active"] = False
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=inactive
    )

    response = frontend(backend).post(
        f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}", data={}
    )

    assert "inactive and cannot be added" in response.text
    assert not any(request.method == "PUT" for request in backend.requests)


def test_inactive_existing_selection_can_still_be_rescheduled(
    backend: FakeBackend,
) -> None:
    inactive = deepcopy(DETAIL)
    inactive["is_active"] = False
    selected = {
        "itineraries": [
            {
                "itinerary_id": TRIP_ID,
                "name": "Sydney Getaway",
                "selected": True,
                "start_date": "2027-04-01",
                "end_date": "2027-04-03",
            }
        ]
    }
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=inactive
    )
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}/itineraries")] = httpx.Response(
        200, json=selected
    )

    response = frontend(backend).post(
        f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}",
        data={"date": "2027-04-03"},
    )

    assert response.status_code == 200
    assert any(request.method == "PUT" for request in backend.requests)


def test_picker_renders_trip_bounds_and_selection_state(backend: FakeBackend) -> None:
    response = frontend(backend).get(f"/activity/{ACTIVITY_ID}/itineraries")

    assert response.status_code == 200
    assert "Sydney Getaway" in response.text
    assert "1 Apr 2027" in response.text
    assert "3 Apr 2027" in response.text
    assert 'min="2027-04-01"' in response.text
    assert 'max="2027-04-03"' in response.text
    assert "Add" in response.text


def test_bodyless_add_uses_backend_default_date(backend: FakeBackend) -> None:
    response = frontend(backend).put(
        f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}", data={}
    )

    request = backend.last_request
    assert request.method == "PUT"
    assert json.loads(request.content) == {}
    assert response.status_code == 200
    assert "Added to this itinerary" in response.text


def test_scheduled_add_forwards_date_and_local_time(backend: FakeBackend) -> None:
    response = frontend(backend).put(
        f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}",
        data={"date": "2027-04-02", "start_time": "09:30"},
    )

    assert json.loads(backend.last_request.content) == {
        "date": "2027-04-02",
        "start_time": "09:30",
    }
    assert "2 Apr 2027" in response.text
    assert "09:30" in response.text
    assert "Update" in response.text


def test_remove_calls_student_4_backend_and_refreshes_picker(
    backend: FakeBackend,
) -> None:
    response = frontend(backend).delete(
        f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}"
    )

    assert backend.last_request.method == "DELETE"
    assert response.status_code == 200
    assert "Add" in response.text


def test_picker_backend_error_stays_inside_picker(backend: FakeBackend) -> None:
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}/itineraries")] = httpx.Response(
        503, json={"detail": "itinerary service unavailable"}
    )

    response = frontend(backend).get(f"/activity/{ACTIVITY_ID}/itineraries")

    assert response.status_code == 200
    assert "The activities service is unavailable" in response.text
    assert "itinerary service unavailable" not in response.text
    assert "activity-dialog" not in response.text
