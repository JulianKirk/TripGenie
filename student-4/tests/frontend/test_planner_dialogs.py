from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
from fastapi.testclient import TestClient
from student4_frontend_service.app import create_app
from student4_frontend_service.config import Settings

from tests.frontend.conftest import ACTIVITY_ID
from tests.frontend.test_planner import RUN
from tests.frontend.test_planner_items import cards, handler_for


def test_approve_opens_read_only_picker_with_required_schedule() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/dialog",
            data={"dialog_approve": ACTIVITY_ID},
            headers={"HX-Request": "true"},
        )
    assert "<dialog" in page.text
    assert "Sydney holiday" in page.text
    assert f'name="date_{ACTIVITY_ID}"' in page.text
    assert "required" in page.text and "optional" not in page.text.lower()
    assert "Confirm approval" in page.text
    assert all(r.method == "GET" for r in requests)


def test_reject_dialog_has_optional_reason_and_one_confirm_action() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/dialog",
            data={"dialog_reject": ACTIVITY_ID},
            headers={"HX-Request": "true"},
        )
    assert "<dialog" in page.text and "Reason (optional)" in page.text
    assert "Confirm rejection" in page.text
    assert all(r.method == "GET" for r in requests)


def test_confirmed_approval_stages_trip_and_schedule_without_backend_write() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={
                "approve_id": ACTIVITY_ID,
                f"trip_{ACTIVITY_ID}": "trip_sydney",
                f"date_{ACTIVITY_ID}": "2027-04-02",
                f"start_time_{ACTIVITY_ID}": "09:30",
            },
            headers={"HX-Request": "true"},
        )
    assert "Approved" in page.text and "Sydney holiday" in page.text
    assert "2027-04-02" in page.text and "09:30" in page.text
    assert all(r.method == "GET" for r in requests)


def test_missing_schedule_cannot_stage_approval() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={"approve_id": ACTIVITY_ID, f"trip_{ACTIVITY_ID}": "trip_sydney"},
            headers={"HX-Request": "true"},
        )
    assert "Choose a date and start time" in page.text
    assert "✓ Approved" not in page.text
    assert all(r.method == "GET" for r in requests)


def test_reject_without_reason_is_staged_and_shows_no_reason_supplied() -> None:
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), []))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/choices",
            data={"reject_id": ACTIVITY_ID},
            headers={"HX-Request": "true"},
        )
    assert "Rejected" in page.text and "no reason supplied" in page.text
    assert "Schedule (optional)" not in page.text
    assert "Reject without reason</button>" not in page.text


def test_cancel_dialog_preserves_pending_choices_without_a_write() -> None:
    requests: list[httpx.Request] = []
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), requests))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/dialog",
            data={
                "cancel": "1",
                f"choice_{ACTIVITY_ID}": "reject",
                f"reason_{ACTIVITY_ID}": "Already visited",
                "reviewer": "Alex",
            },
            headers={"HX-Request": "true"},
        )
    assert "Rejected" in page.text and "Already visited" in page.text
    assert 'value="Alex"' in page.text
    assert all(r.method == "GET" for r in requests)
    assert 'hx-swap-oob="innerHTML"' in page.text


def test_no_javascript_dialog_is_visible_on_catalogue_page() -> None:
    with TestClient(
        create_app(Settings(), transport=handler_for(cards(), []))
    ) as client:
        page = client.post(
            f"/planner/{RUN}/dialog", data={"dialog_reject": ACTIVITY_ID}
        )
    assert "AI activity assistant" in page.text
    assert " open>" in page.text and "Confirm rejection" in page.text
