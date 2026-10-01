"""Release 1: transport lookups through the shared MCP server.

The MCP server is replaced by a JSON-RPC fake behind an injected transport, so
these tests pin this service's side of the contract -- which tool, which
arguments, how each failure surfaces -- without a live host server.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

TRIPS_BASE_URL = "http://student-1-backend:8001"

TRANSPORT_A = "transport_syd_mel_flight"
TRANSPORT_B = "transport_syd_mel_coach"
TRIP = "trip_2027_queenstown_ski_escape"

SEARCH_DATA = {
    "items": [
        {
            "id": TRANSPORT_A,
            "type": "flight",
            "provider": "Jetstar",
            "origin": "Sydney",
            "destination": "Melbourne",
            "price": "129.00",
            "pricing_basis": "per_traveller",
        },
    ],
    "count": 1,
    "truncated": False,
}


def mcp_success(data: dict[str, Any], correlation_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": correlation_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(data)}],
                "structuredContent": {
                    "ok": True,
                    "data": data,
                    "correlation_id": correlation_id,
                    "source": "student-3",
                },
                "isError": False,
            },
        },
    )


def mcp_tool_error(code: str, message: str, correlation_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": correlation_id,
            "result": {
                "content": [{"type": "text", "text": message}],
                "structuredContent": {
                    "ok": False,
                    "error": {"code": code, "message": message, "retryable": False},
                    "correlation_id": correlation_id,
                },
                "isError": True,
            },
        },
    )


Outcome = Callable[[httpx.Request, str], httpx.Response]


@dataclass
class FakeMcp:
    """The shared MCP server's streamable-HTTP endpoint, one tool at a time."""

    outcomes: dict[str, Outcome] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = body["params"]["name"]
        self.calls.append(
            {
                "name": name,
                "arguments": body["params"]["arguments"],
                "method": body["method"],
                "headers": dict(request.headers),
                "url": str(request.url),
            },
        )
        outcome = self.outcomes.get(name)
        if outcome is None:
            return mcp_success({"tool": name}, body["id"])
        return outcome(request, body["id"])


def succeed_with(data: dict[str, Any]) -> Outcome:
    return lambda _request, correlation_id: mcp_success(data, correlation_id)


def fail_tool(code: str, message: str) -> Outcome:
    return lambda _request, correlation_id: mcp_tool_error(
        code, message, correlation_id
    )


def raise_error(exc_type: type[httpx.RequestError]) -> Outcome:
    def outcome(request: httpx.Request, _correlation_id: str) -> httpx.Response:
        raise exc_type("stubbed MCP failure", request=request)

    return outcome


def respond(response: httpx.Response) -> Outcome:
    return lambda _request, _correlation_id: response


@pytest.fixture
def fake_mcp() -> FakeMcp:
    return FakeMcp()


@pytest.fixture
def mcp_settings() -> Settings:
    return Settings(
        database_api_base_url="http://student-3-database:8004",
        trips_api_base_url=TRIPS_BASE_URL,
        mcp_enabled=True,
        mcp_base_url="http://host.docker.internal:8012/mcp",
    )


@pytest.fixture
def mcp_client(
    mcp_settings: Settings,
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
    fake_mcp: FakeMcp,
) -> Iterator[TestClient]:
    app = create_app(
        mcp_settings,
        transport=database_transport,
        trips_transport=itinerary_transport,
        mcp_transport=httpx.MockTransport(fake_mcp.handle),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def disabled_client(
    settings: Settings,
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
    fake_mcp: FakeMcp,
) -> Iterator[TestClient]:
    app = create_app(
        settings,
        transport=database_transport,
        trips_transport=itinerary_transport,
        mcp_transport=httpx.MockTransport(fake_mcp.handle),
    )
    with TestClient(app) as test_client:
        yield test_client


# ----------------------------------------------------------------- health


def test_health_reports_mcp_disabled_by_default(disabled_client: TestClient) -> None:
    for path in ("/health", "/ready"):
        body = disabled_client.get(path).json()["data"]
        assert body["integrations"] == {"mcp": "disabled"}


def test_health_reports_mcp_enabled_without_contacting_it(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.get("/ready")

    assert response.status_code == 200
    assert response.json()["data"]["integrations"] == {"mcp": "enabled"}
    assert fake_mcp.calls == []


# --------------------------------------------------------------- disabled


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/transport-options/mcp/search", {}),
        ("/api/transport-options/mcp/compare", {"ids": [TRANSPORT_A]}),
        (f"/api/trips/{TRIP}/transport/mcp", None),
    ],
)
def test_disabled_mcp_is_an_explicit_503(
    disabled_client: TestClient,
    fake_mcp: FakeMcp,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    response = disabled_client.post(path, json=payload)

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "MCP_DISABLED"
    assert error["message"] == "The MCP tool server is disabled in this environment."
    assert fake_mcp.calls == []


def test_ordinary_transport_routes_work_while_mcp_is_disabled(
    disabled_client: TestClient,
) -> None:
    response = disabled_client.get("/api/transport-options")

    assert response.status_code == 200
    assert response.json()["data"]


# ----------------------------------------------------------------- search


def test_search_calls_transport_search_and_returns_the_tool_data(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    fake_mcp.outcomes["transport_search"] = succeed_with(SEARCH_DATA)

    response = mcp_client.post(
        "/api/transport-options/mcp/search",
        json={"origin": " Sydney ", "destination": "Melbourne", "limit": 3},
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["action"] == "search"
    assert result["tool"] == "transport_search"
    assert result["status"] == "ok"
    assert result["arguments"] == {
        "limit": 3,
        "origin": "Sydney",
        "destination": "Melbourne",
    }
    assert result["data"] == SEARCH_DATA
    assert result["error"] is None
    assert result["persisted"] is False
    assert result["duration_ms"] >= 0

    (call,) = fake_mcp.calls
    assert call["method"] == "tools/call"
    assert call["url"] == "http://host.docker.internal:8012/mcp"
    assert call["arguments"] == result["arguments"]
    assert call["headers"]["accept"] == "application/json, text/event-stream"
    assert call["headers"]["mcp-protocol-version"] == "2025-06-18"
    assert re.fullmatch(r"student3-mcp-[0-9a-f]{12}", call["headers"]["x-request-id"])
    assert result["correlation_id"] == call["headers"]["x-request-id"]


def test_search_sends_only_the_filters_given(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post("/api/transport-options/mcp/search", json={})

    assert response.status_code == 200
    assert fake_mcp.calls[0]["arguments"] == {"limit": 5}


@pytest.mark.parametrize(
    "payload",
    [
        {"origin": "   "},
        {"destination": "x" * 256},
        {"limit": 0},
        {"limit": 21},
        {"tool": "activities_delete"},
        {"mcp_url": "http://evil.example/mcp"},
    ],
)
def test_search_input_is_validated_before_any_tool_call(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
    payload: dict[str, object],
) -> None:
    response = mcp_client.post("/api/transport-options/mcp/search", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_mcp.calls == []


def test_mcp_routes_reject_query_parameters(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post(
        "/api/transport-options/mcp/search?tool=activities_delete",
        json={},
    )

    assert response.status_code == 400
    assert fake_mcp.calls == []


# ---------------------------------------------------------------- compare


def test_compare_calls_transport_compare(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    data = {"items": SEARCH_DATA["items"], "count": 1, "truncated": False}
    fake_mcp.outcomes["transport_compare"] = succeed_with(data)

    response = mcp_client.post(
        "/api/transport-options/mcp/compare",
        json={"ids": [TRANSPORT_A, TRANSPORT_B]},
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["action"] == "compare"
    assert result["tool"] == "transport_compare"
    assert result["data"] == data
    assert fake_mcp.calls[0]["arguments"] == {"ids": [TRANSPORT_A, TRANSPORT_B]}


@pytest.mark.parametrize(
    "ids",
    [
        [],
        [TRANSPORT_A, TRANSPORT_A],
        [
            "transport_a1",
            "transport_b1",
            "transport_c1",
            "transport_d1",
            "transport_e1",
        ],
        ["trip_not_transport"],
    ],
)
def test_compare_ids_are_validated_before_any_tool_call(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
    ids: list[str],
) -> None:
    response = mcp_client.post("/api/transport-options/mcp/compare", json={"ids": ids})

    assert response.status_code == 422
    assert fake_mcp.calls == []


# ------------------------------------------------------------- trip costs


def test_trip_costs_calls_transport_trip_costs(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    data = {
        "trip_id": TRIP,
        "currency": "AUD",
        "entry_count": 0,
        "active_entry_count": 0,
        "estimated_cost_total": "0.00",
        "planned": [],
    }
    fake_mcp.outcomes["transport_trip_costs"] = succeed_with(data)

    response = mcp_client.post(f"/api/trips/{TRIP}/transport/mcp")

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["action"] == "trip-costs"
    assert result["tool"] == "transport_trip_costs"
    assert result["data"] == data
    assert fake_mcp.calls[0]["arguments"] == {"trip_id": TRIP}


def test_trip_costs_rejects_a_malformed_trip_id_before_any_tool_call(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    response = mcp_client.post("/api/trips/not-a-trip/transport/mcp")

    assert response.status_code == 422
    assert fake_mcp.calls == []


# --------------------------------------------------------------- failures


def test_a_tool_that_refuses_is_a_structured_error_result(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    fake_mcp.outcomes["transport_trip_costs"] = fail_tool(
        "NOT_FOUND",
        "Trip was not found",
    )

    response = mcp_client.post(f"/api/trips/{TRIP}/transport/mcp")

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "error"
    assert result["data"] is None
    assert result["error"] == {
        "code": "NOT_FOUND",
        "message": "Trip was not found",
        "retryable": False,
    }


def test_a_rejected_call_without_a_structured_error_is_still_reported(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    fake_mcp.outcomes["transport_search"] = respond(
        httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "result": {
                    "content": [{"type": "text", "text": "Unknown tool"}],
                    "isError": True,
                },
            },
        ),
    )

    response = mcp_client.post("/api/transport-options/mcp/search", json={})

    assert response.status_code == 200
    assert response.json()["data"]["error"]["code"] == "MCP_TOOL_ERROR"


@pytest.mark.parametrize(
    ("outcome", "status_code", "code"),
    [
        (raise_error(httpx.ConnectError), 503, "DEPENDENCY_UNAVAILABLE"),
        (raise_error(httpx.ReadTimeout), 504, "DEPENDENCY_TIMEOUT"),
        (respond(httpx.Response(503)), 503, "DEPENDENCY_UNAVAILABLE"),
        (respond(httpx.Response(500, text="boom")), 502, "BAD_GATEWAY"),
        (respond(httpx.Response(200, text="not json")), 502, "BAD_GATEWAY"),
        (
            respond(
                httpx.Response(
                    200,
                    json={"result": {"structuredContent": {"ok": True}}},
                ),
            ),
            502,
            "BAD_GATEWAY",
        ),
    ],
)
def test_mcp_server_outages_are_dependency_errors(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
    outcome: Outcome,
    status_code: int,
    code: str,
) -> None:
    fake_mcp.outcomes["transport_search"] = outcome

    response = mcp_client.post("/api/transport-options/mcp/search", json={})

    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == code
    assert error["details"] == [
        {"field": "mcp", "issue": f"transport_search: {code}"},
    ]


def test_an_oversized_tool_result_is_refused(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
) -> None:
    fake_mcp.outcomes["transport_search"] = succeed_with({"blob": "x" * 40000})

    response = mcp_client.post("/api/transport-options/mcp/search", json={})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BAD_GATEWAY"


def test_tool_payloads_stay_out_of_the_logs(
    mcp_client: TestClient,
    fake_mcp: FakeMcp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_mcp.outcomes["transport_search"] = succeed_with(SEARCH_DATA)

    with caplog.at_level("INFO", logger="student3_backend_service.service"):
        mcp_client.post(
            "/api/transport-options/mcp/search",
            json={"destination": "Melbourne"},
        )

    logged = caplog.text
    assert "tool=transport_search status=ok" in logged
    assert "Jetstar" not in logged
    assert "Melbourne" not in logged
