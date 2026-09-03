from __future__ import annotations

import json
from copy import deepcopy

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, DETAIL, SUMMARY, FakeBackend
from tests.frontend.test_activity_forms import complete_form, form_post_data


def frontend(backend: FakeBackend) -> TestClient:
    return TestClient(
        create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(backend.handle),
        )
    )


def test_management_lists_inactive_rows_through_backend_query(
    backend: FakeBackend,
) -> None:
    client = frontend(backend)

    response = client.get("/manage")

    query = next(request for request in backend.requests if request.method == "QUERY")
    assert json.loads(query.content)["include_inactive"] is True
    assert response.status_code == 200
    assert "Manage catalogue" in response.text
    assert "Edit" in response.text
    assert "Delete" in response.text


def test_management_paginates_all_catalogue_entries(backend: FakeBackend) -> None:
    backend.overrides[("QUERY", "/activity")] = httpx.Response(
        200,
        json={
            "activities": [SUMMARY],
            "total": 101,
            "limit": 20,
            "offset": 0,
        },
    )

    response = frontend(backend).get("/manage", params={"limit": 20, "offset": 0})

    query = next(request for request in backend.requests if request.method == "QUERY")
    assert json.loads(query.content) == {
        "include_inactive": True,
        "limit": 20,
        "offset": 0,
    }
    assert 'href="/manage?offset=20&amp;limit=20"' in response.text


def test_management_handles_invalid_filter_url_without_500(
    backend: FakeBackend,
) -> None:
    response = frontend(backend).get("/manage", params={"start_time": "09:00"})

    assert response.status_code == 200
    assert "A date is required when filtering by time" in response.text
    assert not any(request.method == "QUERY" for request in backend.requests)


def test_new_form_has_complete_aggregate_controls(backend: FakeBackend) -> None:
    response = frontend(backend).get("/manage/activity/new")

    assert response.status_code == 200
    assert "Create activity" in response.text
    for name in (
        "name",
        "description",
        "price",
        "pricing_basis",
        "duration_minutes",
        "country",
        "city",
        "category",
        "schedules.0.start_time",
    ):
        assert f'name="{name}"' in response.text


def test_edit_form_prefills_complete_activity(backend: FakeBackend) -> None:
    response = frontend(backend).get(f"/manage/activity/{ACTIVITY_ID}/edit")

    assert response.status_code == 200
    assert "Edit activity" in response.text
    assert 'value="Sydney Harbour guided walk"' in response.text
    assert 'value="45.00"' in response.text
    assert 'value="OUTDOOR" checked' in response.text
    assert 'value="09:00"' in response.text


def test_inactive_activity_without_schedules_can_add_one_when_editing(
    backend: FakeBackend,
) -> None:
    inactive = deepcopy(DETAIL)
    inactive["is_active"] = False
    inactive["availability_schedules"] = []
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=inactive
    )

    response = frontend(backend).get(f"/manage/activity/{ACTIVITY_ID}/edit")
    script = frontend(backend).get("/static/js/app.js")

    assert 'name="schedules.0.start_time"' in response.text
    assert 'id="schedule-row-template"' in response.text
    assert "schedule-row-template" in script.text


def test_create_posts_complete_payload_and_redirects(backend: FakeBackend) -> None:
    client = frontend(backend)

    response = client.post(
        "/manage/activity",
        data=form_post_data(complete_form()),
        follow_redirects=False,
    )

    request = next(item for item in backend.requests if item.method == "POST")
    assert response.status_code == 303
    assert response.headers["location"] == f"/manage#activity-{ACTIVITY_ID}"
    assert json.loads(request.content)["price"] == "89.50"
    assert json.loads(request.content)["categories"] == ["ADVENTURE", "OUTDOOR"]


def test_invalid_create_replays_values_in_htmx_form(backend: FakeBackend) -> None:
    form = complete_form(price="10.123")

    response = frontend(backend).post(
        "/manage/activity",
        data=form_post_data(form),
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Create activity" in response.text
    assert 'value="10.123"' in response.text
    assert "canonical decimal" in response.text
    assert not any(request.method == "POST" for request in backend.requests)


def test_edit_uses_complete_put_and_redirects(backend: FakeBackend) -> None:
    response = frontend(backend).post(
        f"/manage/activity/{ACTIVITY_ID}",
        data=form_post_data(complete_form(name="Updated Harbour Kayak")),
        follow_redirects=False,
    )

    request = next(item for item in backend.requests if item.method == "PUT")
    assert json.loads(request.content)["name"] == "Updated Harbour Kayak"
    assert response.status_code == 303


def test_delete_requires_confirmation_then_calls_backend(backend: FakeBackend) -> None:
    client = frontend(backend)

    confirmation = client.get(f"/manage/activity/{ACTIVITY_ID}/delete")

    assert confirmation.status_code == 200
    assert "Permanently delete" in confirmation.text
    assert not any(request.method == "DELETE" for request in backend.requests)

    deleted = client.post(
        f"/manage/activity/{ACTIVITY_ID}/delete", follow_redirects=False
    )
    assert deleted.status_code == 303
    assert any(request.method == "DELETE" for request in backend.requests)


def test_backend_write_error_stays_in_form(backend: FakeBackend) -> None:
    backend.overrides[("POST", "/activity")] = httpx.Response(
        400, json={"detail": "unknown country and city"}
    )

    response = frontend(backend).post(
        "/manage/activity",
        data=form_post_data(complete_form()),
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "unknown country and city" in response.text
    assert 'value="Harbour Kayak"' in response.text
