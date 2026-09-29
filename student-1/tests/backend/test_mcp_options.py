from __future__ import annotations

import json

import httpx
import pytest
from backend_service.config import Settings
from conftest import create_trip_payload

ENABLED = Settings(database_api_base_url="http://database.test", mcp_enabled=True)
TOOLS = [
    "trip_get_context",
    "accommodations_search",
    "activities_search",
    "transport_search",
    "budgets_list",
]


def tool_ok(data: dict[str, object], correlation_id: str = "c-1") -> httpx.Response:
    envelope = {"ok": True, "data": data, "correlation_id": correlation_id}
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": correlation_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(envelope)}],
                "structuredContent": envelope,
                "isError": False,
            },
        },
    )


def tool_error(code: str, retryable: bool = False) -> httpx.Response:
    envelope = {
        "ok": False,
        "error": {"code": code, "message": "Provider failed", "retryable": retryable},
    }
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": "c-1",
            "result": {
                "content": [{"type": "text", "text": json.dumps(envelope)}],
                "structuredContent": envelope,
                "isError": True,
            },
        },
    )


class FakeMcp:
    def __init__(self, overrides: dict[str, httpx.Response | Exception] | None = None):
        self.overrides = overrides or {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.headers: list[httpx.Headers] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        name = body["params"]["name"]
        self.calls.append((name, body["params"]["arguments"]))
        self.headers.append(request.headers)
        response = self.overrides.get(name)
        if isinstance(response, Exception):
            raise response
        return response or tool_ok({"tool": name})


@pytest.fixture
def make(client_factory, database_api):
    def _make(overrides=None, settings=ENABLED):
        mcp = FakeMcp(overrides)
        client = client_factory(
            database_api.handle, settings_override=settings, mcp_handler=mcp.handle
        )
        return client, mcp

    return _make


def _run(client, destination: str, body: object = None) -> tuple[str, httpx.Response]:
    trip = client.post("/api/trips", json=create_trip_payload(destination=destination))
    trip_id = trip.json()["data"]["id"]
    kwargs = {} if body is None else {"json": body}
    return trip_id, client.post(f"/api/trips/{trip_id}/mcp-options", **kwargs)


def test_all_tools_ok_with_exact_names_and_arguments(make) -> None:
    client, mcp = make()
    with client:
        trip_id, response = _run(client, "Sydney, Australia")

    assert response.status_code == 200
    data = response.json()["data"]
    location = {"country": "Australia", "city": "Sydney"}
    assert mcp.calls == [
        ("trip_get_context", {"trip_id": trip_id}),
        ("accommodations_search", {**location, "limit": 5}),
        ("activities_search", {"limit": 5, "filters": {"location": location}}),
        ("transport_search", {"destination": "Sydney", "limit": 5}),
        ("budgets_list", {"trip_id": trip_id, "limit": 5}),
    ]
    assert "budgets_get_summary" not in [name for name, _ in mcp.calls]
    assert data["trip_id"] == trip_id
    assert data["persisted"] is False
    assert data["location"] == {"city": "Sydney", "country": "Australia"}
    assert data["summary"] == {"ok": 5, "error": 0, "skipped": 0}
    assert [r["tool"] for r in data["results"]] == TOOLS
    first = data["results"][0]
    assert first["status"] == "ok"
    assert first["data"] == {"tool": "trip_get_context"}
    assert first["error"] is None
    # One generated correlation id per request, sent on every call.
    ids = {headers["X-Request-ID"] for headers in mcp.headers}
    assert ids == {data["correlation_id"]}
    assert data["correlation_id"].startswith("student1-mcp-")


def test_body_country_is_used_when_destination_has_none(make) -> None:
    client, mcp = make()
    with client:
        _, response = _run(client, "Canberra", {"country": " Australia "})

    assert response.status_code == 200
    assert response.json()["data"]["location"] == {
        "city": "Canberra",
        "country": "Australia",
    }
    assert (
        "accommodations_search",
        {"country": "Australia", "city": "Canberra", "limit": 5},
    ) in mcp.calls


def test_location_searches_are_skipped_without_a_country(make) -> None:
    client, mcp = make()
    with client:
        _, response = _run(client, "Canberra")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["location"] == {"city": "Canberra", "country": None}
    by_tool = {r["tool"]: r for r in data["results"]}
    for tool in ("accommodations_search", "activities_search"):
        assert by_tool[tool]["status"] == "skipped"
        assert "country" in by_tool[tool]["reason"]
    assert [name for name, _ in mcp.calls] == [
        "trip_get_context",
        "transport_search",
        "budgets_list",
    ]
    assert data["summary"] == {"ok": 3, "error": 0, "skipped": 2}


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (tool_error("PROVIDER_UNAVAILABLE", True), "PROVIDER_UNAVAILABLE", True),
        (httpx.ReadTimeout("slow"), "DEPENDENCY_TIMEOUT", True),
        (httpx.Response(200, json={"jsonrpc": "2.0"}), "BAD_GATEWAY", False),
        (httpx.Response(200, text="nope"), "BAD_GATEWAY", False),
        (
            httpx.Response(
                200,
                json={"result": {"structuredContent": {"ok": True, "data": []}}},
            ),
            "BAD_GATEWAY",
            False,
        ),
        (
            httpx.Response(
                200,
                json={
                    "result": {
                        "content": [{"type": "text", "text": "validation error"}],
                        "isError": True,
                    }
                },
            ),
            "MCP_TOOL_ERROR",
            False,
        ),
    ],
)
def test_one_tool_failing_is_partial_not_fatal(make, failure, code, retryable) -> None:
    client, mcp = make({"accommodations_search": failure})
    with client:
        _, response = _run(client, "Sydney, Australia")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"] == {"ok": 4, "error": 1, "skipped": 0}
    failed = data["results"][1]
    assert failed["tool"] == "accommodations_search"
    assert failed["status"] == "error"
    assert failed["data"] is None
    assert failed["error"]["code"] == code
    assert failed["error"]["retryable"] is retryable
    assert len(mcp.calls) == 5


def test_unreachable_mcp_is_503_not_an_empty_success(make) -> None:
    client, _ = make({tool: httpx.ConnectError("down") for tool in TOOLS})
    with client:
        _, response = _run(client, "Sydney, Australia")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DEPENDENCY_UNAVAILABLE"
    assert [d["field"] for d in error["details"]] == TOOLS


def test_all_tool_errors_are_still_reported_per_tool(make) -> None:
    client, _ = make({tool: tool_error("NOT_FOUND") for tool in TOOLS})
    with client:
        _, response = _run(client, "Sydney, Australia")

    assert response.status_code == 200
    assert response.json()["data"]["summary"] == {"ok": 0, "error": 5, "skipped": 0}


def test_disabled_is_an_explicit_error(make) -> None:
    client, mcp = make(settings=Settings(database_api_base_url="http://database.test"))
    with client:
        _, response = _run(client, "Sydney, Australia")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MCP_DISABLED"
    assert mcp.calls == []


def test_unknown_trip_is_404_without_calling_mcp(make) -> None:
    client, mcp = make()
    with client:
        response = client.post("/api/trips/trip_missing/mcp-options")

    assert response.status_code == 404
    assert mcp.calls == []


@pytest.mark.parametrize("body", [{"country": "  "}, {"country": "x" * 101}, {"k": 1}])
def test_invalid_country_is_rejected(make, body) -> None:
    client, mcp = make()
    with client:
        _, response = _run(client, "Canberra", body)

    assert response.status_code == 422
    assert mcp.calls == []
