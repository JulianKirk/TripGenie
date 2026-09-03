from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID, FakeBackend


def test_filter_controls_are_labelled_and_grouped(backend: FakeBackend) -> None:
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    with TestClient(app) as client:
        text = client.get("/").text

    for control in (
        "text",
        "country",
        "city",
        "street",
        "price_min",
        "price_max",
        "duration_min",
        "duration_max",
        "party_size",
        "youngest_age",
        "oldest_age",
        "booking_required",
        "date",
        "start_time",
        "end_time",
        "sort",
        "limit",
    ):
        assert f'for="{control}"' in text
        assert f'id="{control}"' in text
    assert "<fieldset" in text
    assert "<legend>Categories</legend>" in text
    assert "<legend>Required accessibility</legend>" in text


def test_htmx_live_search_and_progressive_submit_share_one_form(
    backend: FakeBackend,
) -> None:
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    with TestClient(app) as client:
        text = client.get("/").text

    assert 'action="/"' in text
    assert 'method="get"' in text
    assert 'hx-get="/activity"' in text
    assert 'hx-trigger="input changed delay:300ms, change"' in text
    assert 'hx-target="#activity-results"' in text
    assert 'hx-swap="innerHTML"' in text
    assert 'type="submit"' in text


def test_dependent_controls_have_a_no_javascript_baseline(backend: FakeBackend) -> None:
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    with TestClient(app) as client:
        text = client.get("/").text

    for control_id in ("city", "category_match", "start_time", "end_time"):
        control = text.split(f'id="{control_id}"', maxsplit=1)[1].split(
            ">", maxsplit=1
        )[0]
        assert "disabled" not in control


def test_activity_name_is_a_button_that_targets_dialog(
    backend: FakeBackend,
) -> None:
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    with TestClient(app) as client:
        text = client.get("/").text

    assert f'hx-get="/activity/{ACTIVITY_ID}"' in text
    assert 'hx-target="#activity-dialog"' in text
    assert '<div id="activity-dialog"' in text
