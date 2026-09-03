from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, SUMMARY, FakeBackend


def frontend(backend: FakeBackend) -> TestClient:
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    return TestClient(app)


def test_index_is_full_htmx_page_with_tripgenie_shell(backend: FakeBackend) -> None:
    client = frontend(backend)
    response = client.get("/")

    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert 'href="http://localhost:8080/theme.css"' in response.text
    assert 'href="http://localhost:8080">Home</a>' in response.text
    assert 'src="https://unpkg.com/htmx.org@2.0.4"' in response.text
    assert 'class="site-header"' in response.text
    assert 'id="activity-filters"' in response.text
    assert 'id="activity-results"' in response.text
    assert 'aria-live="polite"' in response.text
    assert "Sydney Harbour guided walk" in response.text


def test_results_route_is_an_html_fragment(
    backend: FakeBackend,
) -> None:
    client = frontend(backend)
    response = client.get("/activity", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert "Sydney Harbour guided walk" in response.text


def test_filter_form_is_translated_to_backend_query(backend: FakeBackend) -> None:
    client = frontend(backend)

    client.get(
        "/activity",
        params=[
            ("text", "harbour"),
            ("category", "OUTDOOR"),
            ("category", "TOUR"),
            ("price_max", "100"),
        ],
    )

    query_request = next(
        request for request in backend.requests if request.method == "QUERY"
    )
    assert query_request.url.path == "/activity"
    assert json.loads(query_request.content) == {
        "text": "harbour",
        "categories": {"codes": ["OUTDOOR", "TOUR"], "match": "ANY"},
        "price": {"max": "100.00"},
        "include_inactive": True,
        "limit": 20,
        "offset": 0,
    }


def test_cards_render_backend_values_faithfully(backend: FakeBackend) -> None:
    client = frontend(backend)
    text = client.get("/").text

    assert "AUD 45.00" in text
    assert "per person" in text
    assert "2h" in text
    assert "Sydney, Australia" in text
    assert "Outdoor" in text
    assert "Booking required externally" in text
    assert "Accessible toilet" in text


def test_category_failure_keeps_page_and_results_available(
    backend: FakeBackend,
) -> None:
    backend.overrides[("GET", "/activity/categories")] = httpx.Response(
        503, json={"detail": "category service unavailable"}
    )
    client = frontend(backend)

    response = client.get("/")

    assert response.status_code == 200
    assert "Sydney Harbour guided walk" in response.text
    assert "The activities service is unavailable" in response.text
    assert "category service unavailable" not in response.text


def test_empty_results_have_an_explicit_state(backend: FakeBackend) -> None:
    backend.overrides[("QUERY", "/activity")] = httpx.Response(
        200, json={"activities": [], "total": 0, "limit": 20, "offset": 0}
    )
    client = frontend(backend)

    text = client.get("/activity").text

    assert "No activities match these filters" in text
    assert "Add new activity" in text


def test_pager_uses_backend_page_metadata(backend: FakeBackend) -> None:
    backend.overrides[("QUERY", "/activity")] = httpx.Response(
        200,
        json={
            "activities": [SUMMARY],
            "total": 45,
            "limit": 20,
            "offset": 20,
        },
    )
    client = frontend(backend)
    text = client.get("/activity", params={"offset": 20}).text

    assert "Showing 21\N{EN DASH}40 of 45" in text
    assert "Previous" in text
    assert "Next" in text
    assert 'name="offset" value="0"' in text
    assert 'name="offset" value="40"' in text


def test_detail_dialog_renders_full_activity(backend: FakeBackend) -> None:
    client = frontend(backend)
    response = client.get(f"/activity/{ACTIVITY_ID}")

    assert response.status_code == 200
    assert '<dialog class="activity-dialog"' in response.text
    assert "<dialog open" not in response.text
    assert "Arrange at least 24 hours ahead" in response.text
    assert "Circular Quay" in response.text
    assert "Saturday" in response.text
    assert "09:00\N{EN DASH}11:00" in response.text
    assert "1\N{EN DASH}12 participants" in response.text
    assert "Ages 8+" in response.text
    assert "Outdoor" in response.text
    assert "Tour" in response.text
    assert "Add to trip" in response.text
    assert "Unknown" not in response.text
    assert f'aria-label="Edit {SUMMARY["name"]}"' in response.text
    assert response.text.rfind("data-close-dialog") > response.text.find(
        'class="itinerary-section"'
    )


def test_backend_errors_render_safe_results_state(backend: FakeBackend) -> None:
    backend.overrides[("QUERY", "/activity")] = httpx.Response(
        400, json={"detail": "price min must not exceed max"}
    )
    client = frontend(backend)

    response = client.get("/activity")

    assert response.status_code == 200
    assert "price min must not exceed max" in response.text


def test_category_failure_keeps_successful_results_and_detail(
    backend: FakeBackend,
) -> None:
    backend.overrides[("GET", "/activity/categories")] = httpx.Response(
        503, json={"detail": "categories failed"}
    )
    client = frontend(backend)

    results = client.get("/activity")
    detail = client.get(f"/activity/{ACTIVITY_ID}")

    assert "Sydney Harbour guided walk" in results.text
    assert "Sydney Harbour guided walk" in detail.text
    assert "categories failed" not in results.text


def test_health_degrades_when_backend_is_unavailable(backend: FakeBackend) -> None:
    request = httpx.Request("GET", "http://backend.test/health")
    backend.overrides[("GET", "/health")] = httpx.ConnectError(
        "offline", request=request
    )
    client = frontend(backend)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "service": "student-4-frontend",
        "backend": "unavailable",
    }


def test_static_assets_are_served(backend: FakeBackend) -> None:
    client = frontend(backend)

    css = client.get("/static/css/styles.css")
    script = client.get("/static/js/app.js")

    assert css.status_code == 200
    assert ".activity-card" in css.text
    assert script.status_code == 200
    assert "showModal()" in script.text
    assert "syncDependentControls" in script.text


def test_full_page_replays_every_filter_selection(backend: FakeBackend) -> None:
    response = frontend(backend).get(
        "/",
        params={
            "country": "Australia",
            "city": "Sydney",
            "category": "OUTDOOR",
            "category_match": "ALL",
            "booking_required": "false",
            "wheelchair_accessible": "on",
            "date": "2027-04-02",
            "start_time": "09:00",
            "end_time": "12:00",
            "sort": "PRICE_DESC",
            "limit": "50",
        },
    )

    text = response.text
    assert 'id="city" name="city" value="Sydney"' in text
    assert 'value="OUTDOOR" checked' in text
    assert 'value="ALL" selected' in text
    assert 'value="false" selected' in text
    assert 'name="wheelchair_accessible" checked' in text
    assert 'id="start_time" name="start_time" type="time" value="09:00"' in text
    assert 'value="PRICE_DESC" selected' in text
    assert '<option value="50" selected>50</option>' in text


def test_dependent_filter_controls_remain_usable_without_javascript(
    backend: FakeBackend,
) -> None:
    text = frontend(backend).get("/").text

    for control_id in ("city", "category_match", "start_time", "end_time"):
        control = text.split(f'id="{control_id}"', maxsplit=1)[1].split(
            ">", maxsplit=1
        )[0]
        assert "disabled" not in control


def test_clamped_page_size_is_replayed_canonically(backend: FakeBackend) -> None:
    text = frontend(backend).get("/", params={"limit": "999"}).text

    assert '<option value="100" selected>100</option>' in text
