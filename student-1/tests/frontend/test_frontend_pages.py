from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import httpx
import pytest

from .conftest import create_item_form_data, create_trip_form_data

HTMX_HEADERS = {"HX-Request": "true"}


def test_dashboard_renders_full_page_theme_and_accessible_controls(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "Trip &amp; Itinerary Management" in response.text
    assert 'id="trip-list-heading"' in response.text
    assert 'id="filter-date"' in response.text
    assert 'id="filter-category"' in response.text
    assert 'id="ai-requested-date"' in response.text
    assert 'id="ai-goal"' in response.text
    assert 'id="ai-interests"' in response.text
    assert 'id="ai-constraints"' in response.text
    assert 'role="status"' in response.text
    assert "Generate draft suggestions" in response.text
    assert "persisted=false" in response.text
    assert "Delete trip" in response.text
    assert 'href="http://localhost:8080/theme.css"' in response.text
    assert 'href="http://testserver/static/css/styles.css"' in response.text
    assert 'src="http://testserver/static/js/htmx.min.js"' in response.text
    assert "unpkg.com" not in response.text
    assert 'class="skip-link" href="#app-shell"' in response.text
    assert '<nav class="panel panel--sidebar"' in response.text
    assert 'href="http://localhost:8080">Home</a>' in response.text


def test_theme_and_local_assets_follow_the_shared_contract(
    client,
    client_factory,
) -> None:
    page = client.get("/")
    css = client.get("/static/css/styles.css")
    htmx = client.get("/static/js/htmx.min.js")

    shared_theme_link = 'href="http://localhost:8080/theme.css"'
    local_stylesheet_link = 'href="http://testserver/static/css/styles.css"'
    assert page.text.index(shared_theme_link) < page.text.index(local_stylesheet_link)
    assert "Trip &amp; Itinerary Management" in page.text
    assert "Generate draft suggestions" in page.text
    assert "Selected transport" in page.text
    assert "Selected activities" in page.text
    assert "Accommodations" in page.text
    assert css.status_code == 200
    assert "--page-bg: var(--tg-canvas, #f2f5f3);" in css.text
    assert "--primary: var(--tg-accent, #08785d);" in css.text
    assert '--font-body: var(--tg-font-body, Georgia, "Times New Roman", serif);' in (
        css.text
    )
    assert "outline: none;" not in css.text
    assert htmx.status_code == 200
    assert "htmx" in htmx.text

    with client_factory(root_path="/tripgenie/student-1") as prefixed_client:
        page = prefixed_client.get("/")

    assert page.status_code == 200
    assert (
        'href="http://testserver/tripgenie/student-1/static/css/styles.css"'
        in page.text
    )
    assert (
        'src="http://testserver/tripgenie/student-1/static/js/htmx.min.js"' in page.text
    )
    assert 'src="http://testserver/tripgenie/student-1/static/js/app.js"' in page.text


def test_htmx_trip_navigation_returns_shell_fragment_only(client) -> None:
    response = client.get(
        "/trips/trip_2027_sydney_getaway",
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text
    assert '<main\n  id="app-shell"' in response.text
    assert "Sydney Getaway" in response.text


def test_empty_state_renders_when_no_trips(client, backend_api) -> None:
    backend_api.trips.clear()
    backend_api.items.clear()

    response = client.get("/")

    assert response.status_code == 200
    assert "Plan your first trip" in response.text
    assert "Create trip" in response.text
    assert "AI draft suggestions unlock after you create a trip" in response.text


def test_trip_create_success_redirects_for_full_page_and_swaps_for_htmx(client) -> None:
    full_page_response = client.post(
        "/trips",
        data=create_trip_form_data(
            id="trip_frontend_full_page_01",
            name="Frontend Full Page Create",
        ),
        follow_redirects=False,
    )

    assert full_page_response.status_code == 303
    assert full_page_response.headers["location"] == "/trips/trip_frontend_full_page_01"

    redirected = client.get(full_page_response.headers["location"])
    assert redirected.status_code == 200
    assert "Frontend Full Page Create" in redirected.text

    htmx_response = client.post(
        "/trips",
        data=create_trip_form_data(
            id="trip_frontend_htmx_create_01",
            name="Frontend HTMX Create",
        ),
        headers=HTMX_HEADERS,
    )

    assert htmx_response.status_code == 201
    assert htmx_response.headers["HX-Push-Url"] == "/trips/trip_frontend_htmx_create_01"
    assert "<!DOCTYPE html>" not in htmx_response.text
    assert "Frontend HTMX Create" in htmx_response.text


def test_trip_form_validation_preserves_values_and_field_errors(client) -> None:
    response = client.post(
        "/trips",
        data=create_trip_form_data(
            id="trip_invalid_01",
            name="Broken Planner",
            destination="Broken City",
            start_date="2027-05-05",
            end_date="2027-05-01",
            traveller_count="0",
        ),
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 422
    assert "One or more fields failed validation." in response.text
    assert 'value="Broken Planner"' in response.text
    assert 'value="Broken City"' in response.text
    assert 'value="0"' in response.text
    assert "start_date: must be on or before end_date" in response.text
    assert (
        "traveller_count: Input should be greater than or equal to 1" in response.text
    )


def test_trip_edit_and_delete_confirmation_flow(client) -> None:
    edit_form = client.get("/trips/trip_2027_sydney_getaway/edit")
    assert edit_form.status_code == 200
    assert 'value="Sydney Getaway"' in edit_form.text

    update_response = client.post(
        "/trips/trip_2027_sydney_getaway/edit",
        data=create_trip_form_data(
            name="Sydney Harbour Escape",
            destination="Sydney Harbour",
            start_date="2027-04-01",
            end_date="2027-04-04",
            traveller_count="4",
            status="active",
            notes="Updated trip note.",
        ),
        headers=HTMX_HEADERS,
    )

    assert update_response.status_code == 200
    assert update_response.headers["HX-Push-Url"] == "/trips/trip_2027_sydney_getaway"
    assert "Sydney Harbour Escape" in update_response.text
    assert "Sydney Harbour" in update_response.text
    assert "Updated trip note." in update_response.text

    confirmation = client.get("/trips/trip_2027_sydney_getaway/delete")
    assert confirmation.status_code == 200
    assert "Delete &#39;Sydney Harbour Escape&#39;?" in confirmation.text
    assert "Delete trip" in confirmation.text

    delete_response = client.post(
        "/trips/trip_2027_sydney_getaway/delete",
        data={"trip_name": "Sydney Harbour Escape"},
        follow_redirects=False,
    )

    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/trips/trip_2027_tokyo_city_break"
    after_delete = client.get(delete_response.headers["location"])
    assert "Tokyo City Break" in after_delete.text
    assert "Sydney Harbour Escape" not in after_delete.text


def test_item_create_edit_delete_flows_and_selected_day_view(client) -> None:
    create_response = client.post(
        "/trips/trip_2027_sydney_getaway/items",
        data=create_item_form_data(
            id="item_frontend_breakfast_01",
            date="2027-04-02",
            start_time="08:00",
            end_time="09:00",
            title="Breakfast Booking",
            category="meal",
        ),
        headers=HTMX_HEADERS,
    )

    assert create_response.status_code == 200
    assert (
        create_response.headers["HX-Push-Url"]
        == "/trips/trip_2027_sydney_getaway/days/2027-04-02"
    )
    assert "Breakfast Booking" in create_response.text

    selected_day = client.get("/trips/trip_2027_sydney_getaway/days/2027-04-02")
    breakfast_position = selected_day.text.index("Breakfast Booking")
    harbour_walk_position = selected_day.text.index("Harbour Walk")
    assert breakfast_position < harbour_walk_position

    edit_form = client.get("/items/item_frontend_breakfast_01/edit")
    assert edit_form.status_code == 200
    assert 'value="Breakfast Booking"' in edit_form.text
    assert 'name="trip_id" value="trip_2027_sydney_getaway"' in edit_form.text

    update_response = client.post(
        "/items/item_frontend_breakfast_01/edit",
        data={
            "trip_id": "trip_2027_sydney_getaway",
            **create_item_form_data(
                date="2027-04-02",
                start_time="08:00",
                end_time="09:15",
                title="Breakfast Booking",
                category="meal",
                notes="Confirm vegetarian option.",
            ),
        },
        headers=HTMX_HEADERS,
    )

    assert update_response.status_code == 200
    assert "Confirm vegetarian option." in update_response.text
    assert "09:15" in update_response.text

    delete_confirmation = client.get("/items/item_frontend_breakfast_01/delete")
    assert delete_confirmation.status_code == 200
    assert "Delete itinerary item" in delete_confirmation.text
    assert "Breakfast Booking" in delete_confirmation.text

    delete_response = client.post(
        "/items/item_frontend_breakfast_01/delete",
        data={
            "trip_id": "trip_2027_sydney_getaway",
            "item_date": "2027-04-02",
            "item_title": "Breakfast Booking",
        },
        follow_redirects=False,
    )

    assert delete_response.status_code == 303
    assert (
        delete_response.headers["location"]
        == "/trips/trip_2027_sydney_getaway/days/2027-04-02"
    )
    after_delete = client.get(delete_response.headers["location"])
    assert "Breakfast Booking" not in after_delete.text


def test_item_form_validation_preserves_values_and_errors(client) -> None:
    response = client.post(
        "/trips/trip_2027_sydney_getaway/items",
        data=create_item_form_data(
            id="item_invalid_time_01",
            date="2027-04-02",
            start_time="11:00",
            end_time="10:00",
            title="Invalid Walk",
            category="activity",
            notes="Keep this value visible.",
        ),
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 422
    assert "One or more fields failed validation." in response.text
    assert 'value="Invalid Walk"' in response.text
    assert 'value="11:00"' in response.text
    assert 'value="10:00"' in response.text
    assert "Keep this value visible." in response.text
    assert (
        "start_time: must be earlier than end_time when both are provided"
        in response.text
    )


def test_trip_detail_filters_by_date_and_category(client) -> None:
    client.post(
        "/trips",
        data=create_trip_form_data(
            id="trip_filter_trip_01",
            name="Filter Trip",
            start_date="2027-06-01",
            end_date="2027-06-03",
        ),
    )
    client.post(
        "/trips/trip_filter_trip_01/items",
        data=create_item_form_data(
            id="item_filter_trip_01_breakfast",
            date="2027-06-02",
            start_time="08:00",
            end_time="09:00",
            title="Breakfast Booking",
            category="meal",
        ),
    )
    client.post(
        "/trips/trip_filter_trip_01/items",
        data=create_item_form_data(
            id="item_filter_trip_01_note",
            date="2027-06-02",
            start_time="",
            end_time="",
            title="Parking Reminder",
            category="note",
        ),
    )
    client.post(
        "/trips/trip_filter_trip_01/items",
        data=create_item_form_data(
            id="item_filter_trip_01_walk",
            date="2027-06-01",
            start_time="10:00",
            end_time="11:00",
            title="Lake Walk",
            category="activity",
        ),
    )

    response = client.get(
        "/trips/trip_filter_trip_01?date=2027-06-02&category=meal",
    )

    assert response.status_code == 200
    assert "Breakfast Booking" in response.text
    assert "Parking Reminder" not in response.text
    assert "Lake Walk" not in response.text
    assert 'value="2027-06-02"' in response.text
    assert '<option value="meal" selected>' in response.text


def test_htmx_filter_gets_push_history_url_and_refreshable_state(client) -> None:
    client.post(
        "/trips",
        data=create_trip_form_data(
            id="trip_history_trip_01",
            name="History Trip",
            start_date="2027-06-01",
            end_date="2027-06-03",
        ),
    )
    client.post(
        "/trips/trip_history_trip_01/items",
        data=create_item_form_data(
            id="item_history_trip_01_breakfast",
            date="2027-06-02",
            start_time="08:00",
            end_time="09:00",
            title="Breakfast Booking",
            category="meal",
        ),
    )
    client.post(
        "/trips/trip_history_trip_01/items",
        data=create_item_form_data(
            id="item_history_trip_01_walk",
            date="2027-06-01",
            start_time="10:00",
            end_time="11:00",
            title="Lake Walk",
            category="activity",
        ),
    )

    response = client.get(
        "/trips/trip_history_trip_01?date=2027-06-02&category=meal",
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 200
    assert (
        response.headers["HX-Push-Url"]
        == "/trips/trip_history_trip_01?date=2027-06-02&category=meal"
    )
    assert "Breakfast Booking" in response.text
    assert "Lake Walk" not in response.text
    assert 'value="2027-06-02"' in response.text
    assert '<option value="meal" selected>' in response.text

    refresh_response = client.get(response.headers["HX-Push-Url"])
    assert refresh_response.status_code == 200
    assert "Breakfast Booking" in refresh_response.text
    assert "Lake Walk" not in refresh_response.text
    assert 'value="2027-06-02"' in refresh_response.text
    assert '<option value="meal" selected>' in refresh_response.text


def test_invalid_htmx_filter_keeps_history_state_but_uses_safe_add_item_link(
    client,
) -> None:
    response = client.get(
        "/trips/trip_2027_sydney_getaway?date=20270402&category=meal",
        headers=HTMX_HEADERS,
    )

    assert response.status_code == 422
    assert (
        response.headers["HX-Push-Url"]
        == "/trips/trip_2027_sydney_getaway?date=20270402&category=meal"
    )
    assert 'value="20270402"' in response.text
    assert '<option value="meal" selected>' in response.text
    assert "items/new?date=2027-04-01" in response.text
    assert "20270402" not in response.text.split("items/new?date=")[1].split('"', 1)[0]

    refresh_response = client.get(response.headers["HX-Push-Url"])
    assert refresh_response.status_code == 422
    assert 'value="20270402"' in refresh_response.text
    assert "items/new?date=2027-04-01" in refresh_response.text


def test_new_item_form_defaults_invalid_query_date_to_trip_start(client) -> None:
    response = client.get("/trips/trip_2027_sydney_getaway/items/new?date=20270402")

    assert response.status_code == 422
    assert "The requested itinerary date could not be applied." in response.text
    assert "must be a valid ISO date in YYYY-MM-DD format" in response.text
    assert 'id="item-date"' in response.text
    assert 'value="2027-04-01"' in response.text
    assert 'href="/trips/trip_2027_sydney_getaway"' in response.text
    assert 'href="/trips/trip_2027_sydney_getaway/days/20270402"' not in response.text


def test_new_item_form_defaults_out_of_range_query_date_to_trip_start(client) -> None:
    response = client.get("/trips/trip_2027_sydney_getaway/items/new?date=2027-04-05")

    assert response.status_code == 422
    assert "The requested itinerary date could not be applied." in response.text
    assert "must fall between 2027-04-01 and 2027-04-03" in response.text
    assert 'value="2027-04-01"' in response.text
    assert 'href="/trips/trip_2027_sydney_getaway"' in response.text
    assert 'href="/trips/trip_2027_sydney_getaway/days/2027-04-05"' not in response.text


def test_new_item_form_accepts_valid_boundary_query_date(client) -> None:
    response = client.get("/trips/trip_2027_sydney_getaway/items/new?date=2027-04-03")

    assert response.status_code == 200
    assert "The requested itinerary date could not be applied." not in response.text
    assert 'value="2027-04-03"' in response.text
    assert 'href="/trips/trip_2027_sydney_getaway/days/2027-04-03"' in response.text


@pytest.mark.anyio
async def test_async_write_requests_overlap(async_client_factory, backend_api) -> None:
    class OverlapHandler:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.second_started = asyncio.Event()
            self.release = asyncio.Event()
            self.in_flight = 0
            self.max_in_flight = 0

        async def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/trips":
                self.in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self.in_flight)
                try:
                    if not self.first_started.is_set():
                        self.first_started.set()
                        await asyncio.wait_for(self.second_started.wait(), timeout=1)
                    else:
                        self.second_started.set()

                    await asyncio.wait_for(self.release.wait(), timeout=1)
                    return backend_api.handle(request)
                finally:
                    self.in_flight -= 1

            return backend_api.handle(request)

    overlap_handler = OverlapHandler()

    async with async_client_factory(overlap_handler) as client:
        first_request = asyncio.create_task(
            client.post(
                "/trips",
                data=create_trip_form_data(
                    id="trip_async_overlap_01",
                    name="Async Overlap One",
                ),
            )
        )
        await asyncio.wait_for(overlap_handler.first_started.wait(), timeout=1)

        second_request = asyncio.create_task(
            client.post(
                "/trips",
                data=create_trip_form_data(
                    id="trip_async_overlap_02",
                    name="Async Overlap Two",
                ),
            )
        )

        await asyncio.wait_for(overlap_handler.second_started.wait(), timeout=1)
        assert overlap_handler.max_in_flight == 2

        overlap_handler.release.set()
        first_response, second_response = await asyncio.gather(
            first_request,
            second_request,
        )

    assert first_response.status_code == 303
    assert second_response.status_code == 303
    assert first_response.headers["location"] == "/trips/trip_async_overlap_01"
    assert second_response.headers["location"] == "/trips/trip_async_overlap_02"


def test_dependency_failures_and_malformed_backend_responses_are_explicit(
    client_factory,
) -> None:
    with client_factory(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError("boom", request=request),
        ),
    ) as unavailable_client:
        unavailable_response = unavailable_client.get("/")

    assert unavailable_response.status_code == 503
    assert "Student 1 trips are unavailable" in unavailable_response.text
    assert "Backend API is unavailable." in unavailable_response.text

    with client_factory(
        lambda request: (_ for _ in ()).throw(
            httpx.ReadTimeout("slow", request=request),
        ),
    ) as timeout_client:
        timeout_response = timeout_client.get("/")

    assert timeout_response.status_code == 504
    assert (
        "Backend API did not respond before the configured timeout."
        in timeout_response.text
    )

    with client_factory(
        lambda request: httpx.Response(200, text="{not json"),
    ) as malformed_client:
        malformed_response = malformed_client.get("/")

    assert malformed_response.status_code == 502
    assert (
        "Backend API returned a malformed trip list response."
        in malformed_response.text
    )


def test_health_and_ready_reflect_backend_dependency_statuses(
    client,
    client_factory,
    backend_api,
) -> None:
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {
        "data": {
            "status": "ok",
            "service": "student-1-frontend",
            "dependencies": {
                "backend": {
                    "status": "ok",
                    "service": "student-1-backend",
                    "detail": "Backend API responded successfully.",
                    "code": None,
                },
            },
        },
    }

    ready_response = client.get("/ready")
    assert ready_response.status_code == 200
    assert ready_response.json()["data"]["status"] == "ok"

    backend_api.ready_status_code = 503
    backend_api.ready_payload["status"] = "unavailable"

    with client_factory() as degraded_client:
        degraded_ready = degraded_client.get("/ready")

    assert degraded_ready.status_code == 503
    assert degraded_ready.json() == {
        "data": {
            "status": "unavailable",
            "service": "student-1-frontend",
            "dependencies": {
                "backend": {
                    "status": "unavailable",
                    "service": "student-1-backend",
                    "detail": "Backend API reported it is not ready yet.",
                    "code": None,
                },
            },
        },
    }


def test_frontend_service_has_no_direct_sqlite_access() -> None:
    package_root = Path(__file__).resolve().parents[2] / "frontend" / "frontend_service"
    offending_imports: list[str] = []

    for file_path in package_root.rglob("*.py"):
        module = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sqlite3" or alias.name.startswith("sqlite3."):
                        offending_imports.append(str(file_path))
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                offending_imports.append(str(file_path))

    assert offending_imports == []
