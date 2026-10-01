"""Release 1: the MCP tools page, through the real backend to a fake MCP server."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_frontend_service.app import create_app as create_frontend_app
from student3_frontend_service.config import Settings as FrontendSettings

from tests.frontend.conftest import _build_backend

TRIP = "trip_2026_sydney_long_weekend"

SEARCH_DATA = {
    "items": [
        {
            "id": "transport_mcp_flight",
            "type": "flight",
            "provider": "Skyline Air",
            "origin": "Sydney",
            "destination": "Melbourne",
            "departure_time": "2026-10-02T07:00",
            "price": "129.00",
            "pricing_basis": "per_traveller",
            "seats_remaining": None,
        },
    ],
    "count": 1,
    "truncated": False,
}

TRIP_COSTS_DATA = {
    "trip_id": TRIP,
    "currency": "AUD",
    "entry_count": 1,
    "active_entry_count": 1,
    "estimated_cost_total": "258.00",
    "planned": [
        {
            "entry": {
                "transport_id": "transport_mcp_flight",
                "traveller_count": 2,
                "plan_status": "pending",
            },
            "option": {
                "id": "transport_mcp_flight",
                "origin": "Sydney",
                "destination": "Melbourne",
                "provider": "Skyline Air",
                "price": "129.00",
                "pricing_basis": "per_traveller",
            },
            "estimated_cost": "258.00",
        },
    ],
}


class FakeMcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.refuse: dict[str, tuple[str, str]] = {}
        self.unreachable = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            message = "connection refused"
            raise httpx.ConnectError(message, request=request)
        body = json.loads(request.content)
        name = body["params"]["name"]
        self.calls.append((name, body["params"]["arguments"]))
        if name in self.refuse:
            code, message = self.refuse[name]
            structured: dict[str, Any] = {
                "ok": False,
                "error": {"code": code, "message": message, "retryable": False},
            }
        else:
            data = {
                "transport_search": SEARCH_DATA,
                "transport_compare": SEARCH_DATA,
                "transport_trip_costs": TRIP_COSTS_DATA,
            }[name]
            structured = {"ok": True, "data": data, "correlation_id": body["id"]}
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [],
                    "structuredContent": structured,
                    "isError": not structured["ok"],
                },
            },
        )


@pytest.fixture
def fake_mcp() -> FakeMcp:
    return FakeMcp()


@pytest.fixture
def mcp_client(
    frontend_settings: FrontendSettings,
    database_path: Path,
    trips_transport: httpx.MockTransport,
    fake_mcp: FakeMcp,
) -> Iterator[TestClient]:
    for backend_app in _build_backend(
        database_path,
        trips_transport,
        mcp_transport=httpx.MockTransport(fake_mcp.handle),
    ):
        app = create_frontend_app(
            frontend_settings,
            transport=httpx.ASGITransport(app=backend_app),
        )
        with TestClient(app) as test_client:
            yield test_client


def _collapsed(response: httpx.Response) -> str:
    return " ".join(response.text.split())


def test_tools_page_offers_each_registered_transport_tool(
    mcp_client: TestClient,
) -> None:
    response = mcp_client.get("/tools")

    assert response.status_code == 200
    for tool in ("transport_search", "transport_compare", "transport_trip_costs"):
        assert tool in response.text
    assert "Nothing is saved" in response.text


def test_mcp_link_is_in_the_shell_navigation(client: TestClient) -> None:
    assert "MCP tools" in client.get("/").text


def test_search_shows_the_structured_tool_result(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post(
        "/tools/search",
        data={"origin": "Sydney", "destination": "", "limit": "3"},
    )

    assert response.status_code == 200
    assert fake_mcp.calls == [("transport_search", {"limit": 3, "origin": "Sydney"})]
    text = _collapsed(response)
    assert "Tool result" in text
    assert "<code>transport_search</code>" in text
    assert "Skyline Air" in text
    assert "$129.00 per traveller" in text
    assert "unknown" in text  # seats_remaining: null is unknown, not zero
    assert "Structured tool result" in text
    assert "nothing was saved" in text
    assert "student3-mcp-" in text


def test_compare_offers_a_checkbox_list_not_dropdowns(
    mcp_client: TestClient,
) -> None:
    text = _collapsed(mcp_client.get("/tools"))

    assert "Choose up to 4 options" in text
    assert 'type="checkbox" name="ids" value="transport_' in text
    assert 'name="id_1"' not in text


def test_compare_sends_every_ticked_option(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post(
        "/tools/compare",
        data={"ids": ["transport_mcp_flight", "transport_mcp_coach"]},
    )

    assert response.status_code == 200
    assert fake_mcp.calls == [
        ("transport_compare", {"ids": ["transport_mcp_flight", "transport_mcp_coach"]}),
    ]
    assert "<code>transport_compare</code>" in response.text


def test_compare_keeps_the_ticked_options_after_running(
    mcp_client: TestClient,
) -> None:
    listed = _collapsed(mcp_client.get("/tools"))
    first = listed.split('name="ids" value="', 1)[1].split('"', 1)[0]

    response = mcp_client.post("/tools/compare", data={"ids": [first]})

    assert f'value="{first}" checked' in _collapsed(response)


def test_compare_with_nothing_ticked_is_refused_before_mcp(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post("/tools/compare", data={})

    assert "VALIDATION_ERROR" in response.text
    assert fake_mcp.calls == []


def test_compare_with_more_than_four_ticked_is_refused_before_mcp(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    ids = [f"transport_mcp_{name}" for name in ("a1", "b1", "c1", "d1", "e1")]

    response = mcp_client.post("/tools/compare", data={"ids": ids})

    assert "VALIDATION_ERROR" in response.text
    assert fake_mcp.calls == []


def test_trip_costs_shows_the_trip_total(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post("/tools/trip-costs", data={"trip_id": TRIP})

    assert response.status_code == 200
    assert fake_mcp.calls == [("transport_trip_costs", {"trip_id": TRIP})]
    text = _collapsed(response)
    assert "258.00 AUD" in text
    assert "Sydney &rarr; Melbourne" in text
    # The trip's name is shown, with its id beneath it rather than instead.
    assert (
        '<dt>Trip</dt><dd> Sydney Long Weekend <span class="mcp-result__id">'
        f"<code>{TRIP}</code></span>"
    ) in text


def test_trip_transport_page_links_to_the_mcp_cost_check(
    mcp_client: TestClient,
) -> None:
    response = mcp_client.get(f"/trips/{TRIP}/transport")

    assert response.status_code == 200
    assert 'action="http://testserver/tools/trip-costs"' in response.text
    assert "Check costs via MCP" in response.text


def test_an_invalid_trip_id_is_refused_without_calling_the_backend(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post("/tools/trip-costs", data={"trip_id": "../health"})

    assert response.status_code == 200
    assert "Choose a trip" in response.text
    assert fake_mcp.calls == []


def test_a_tool_refusal_is_shown_as_a_tool_result(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    fake_mcp.refuse["transport_trip_costs"] = ("NOT_FOUND", "Trip was not found")

    response = mcp_client.post("/tools/trip-costs", data={"trip_id": TRIP})

    text = _collapsed(response)
    assert "The tool ran and refused: NOT_FOUND" in text
    assert "Trip was not found" in text


def test_an_unreachable_mcp_server_is_explained(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    fake_mcp.unreachable = True

    response = mcp_client.post("/tools/search", data={"origin": "Sydney"})

    assert response.status_code == 200
    text = _collapsed(response)
    assert "DEPENDENCY_UNAVAILABLE" in text
    assert "python -m tripgenie_mcp serve" in text


def test_backend_validation_errors_are_shown_on_the_form(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post("/tools/search", data={"limit": "99"})

    assert "VALIDATION_ERROR" in response.text
    assert fake_mcp.calls == []


def test_unknown_actions_are_refused(mcp_client: TestClient, fake_mcp: FakeMcp) -> None:
    response = mcp_client.post("/tools/activities_delete", data={})

    assert "Unknown MCP action" in response.text
    assert fake_mcp.calls == []


def test_disabled_mcp_is_shown_as_disabled(client: TestClient) -> None:
    response = client.post("/tools/search", data={"origin": "Sydney"})

    assert response.status_code == 200
    text = _collapsed(response)
    assert "MCP_DISABLED" in text
    assert "disabled in this environment" in text
    assert "Browsing, comparing and planning still work" in text
