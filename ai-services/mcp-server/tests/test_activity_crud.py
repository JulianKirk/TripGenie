import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from tripgenie_mcp.config import Settings
from tripgenie_mcp.provider import ProviderClient
from tripgenie_mcp.server import create_app, create_server

ID = "5ad9845c-a7d1-5688-b06a-63e92bed4345"
WRITE = {
    "name": "Museum",
    "description": "Visit",
    "price": "12.50",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 60,
    "minimum_participants": 1,
    "categories": ["CULTURE"],
    "location_details": {"country": "Australia", "city": "Sydney"},
    "availability_schedules": [
        {
            "recurring_weekly": True,
            "day_of_week": "MONDAY",
            "start_time": "09:00",
            "end_time": "17:00",
        }
    ],
}
DETAIL = WRITE | {
    "id": ID,
    "availability_schedules": [WRITE["availability_schedules"][0] | {"id": ID}],
}


def server_for(payload, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)

    provider = ProviderClient(
        {"student-4": "http://activities.test"}, httpx.MockTransport(handler)
    )
    return create_server(Settings(), provider), requests


def call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    return (
        result.structuredContent if hasattr(result, "structuredContent") else result[1]
    )


def test_search_advanced_filters_and_offset():
    server, requests = server_for(
        {"activities": [], "total": 5, "limit": 5, "offset": 5}
    )
    result = call(
        server,
        "activities_search",
        {
            "text": "museum",
            "limit": 5,
            "offset": 5,
            "filters": {
                "location": {"country": "Australia", "city": "Sydney"},
                "price": {"max": "20.00"},
                "accessibility": {"wheelchair_accessible": True},
            },
        },
    )
    assert result["ok"] is True
    assert result["data"]["truncated"] is False
    assert json.loads(requests[0].content) == {
        "text": "museum",
        "limit": 5,
        "offset": 5,
        "location": {"country": "Australia", "city": "Sydney"},
        "price": {"max": "20.00"},
        "accessibility": {"wheelchair_accessible": True},
    }


@pytest.mark.parametrize(
    ("name", "args", "status", "method", "path", "response"),
    [
        ("activities_create", {"activity": WRITE}, 201, "POST", "/activity", DETAIL),
        (
            "activities_update",
            {"activity_id": ID, "activity": WRITE},
            200,
            "PUT",
            f"/activity/{ID}",
            DETAIL,
        ),
        (
            "activities_delete",
            {"activity_id": ID, "confirm": True},
            200,
            "DELETE",
            f"/activity/{ID}",
            {"id": ID, "deleted": True},
        ),
    ],
)
def test_activity_writes(name, args, status, method, path, response):
    server, requests = server_for(response, status)
    result = call(server, name, args)
    assert result["ok"] is True
    assert result["data"]["id"] == ID
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == path
    if method != "DELETE":
        assert json.loads(requests[0].content)["price"] == "12.50"
        assert result["data"]["wheelchair_accessible"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"price": 12.5},
        {"price": "12.5"},
        {"duration_minutes": True},
        {"categories": ["CULTURE", "CULTURE"]},
        {"minimum_age": 20, "maximum_age": 10},
        {"availability_schedules": []},
        {"duration_minutes": 600},
        {"location_details": {"country": "Australia"}},
    ],
)
def test_invalid_writes_never_reach_provider(changes):
    server, requests = server_for(DETAIL, 201)
    with pytest.raises(ToolError):
        call(server, "activities_create", {"activity": deepcopy(WRITE) | changes})
    assert requests == []


@pytest.mark.parametrize(
    "filters",
    [
        {"text": "hidden"},
        {"limit": 100},
        {"offset": 2},
        {"location": {"city": "Sydney"}},
        {"price": {"min": "20.00", "max": "10.00"}},
        {"youngest_age": 20, "oldest_age": 10},
        {"availability": {"date": "2026-09-28", "start_time": "09:00"}},
    ],
)
def test_invalid_filters_never_reach_provider(filters):
    server, requests = server_for({})
    with pytest.raises(ToolError):
        call(server, "activities_search", {"filters": filters})
    assert requests == []


def test_delete_requires_explicit_true():
    server, requests = server_for({"id": ID, "deleted": True})
    for args in ({"activity_id": ID}, {"activity_id": ID, "confirm": False}):
        with pytest.raises(ToolError):
            call(server, "activities_delete", args)
    assert not requests


@pytest.mark.parametrize(
    "payload,status",
    [(httpx.ReadTimeout("lost response"), 200), ({}, 503), ("bad", 201)],
)
def test_write_uncertain_outcomes_are_not_retried(payload, status):
    server, requests = server_for(payload, status)
    result = call(server, "activities_create", {"activity": WRITE})
    assert result["ok"] is False
    assert result["error"]["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert result["error"]["retryable"] is False
    assert len(requests) == 1


def test_delete_rejects_wrong_id_and_false_confirmation_from_provider():
    for response in ({"id": ID, "deleted": False}, {"id": "bad", "deleted": True}):
        server, _ = server_for(response)
        result = call(server, "activities_delete", {"activity_id": ID, "confirm": True})
        assert result["ok"] is False
        assert result["error"]["code"] == "WRITE_OUTCOME_UNKNOWN"


def test_registered_schemas_and_annotations():
    server, _ = server_for({})
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name in ("activities_create", "activities_update", "activities_delete"):
        assert tools[name].annotations.readOnlyHint is False
    assert tools["activities_delete"].annotations.destructiveHint is True
    assert tools["activities_search"].annotations.readOnlyHint is True
    schema = tools["activities_create"].inputSchema
    assert schema["properties"]["activity"]["$ref"]
    assert schema["$defs"]["ActivityWrite"]["additionalProperties"] is False
    assert schema["$defs"]["ActivityWrite"]["properties"]["price"]["type"] == "string"


def test_streamable_http_protocol_and_request_correlation():
    from tripgenie_mcp.server import create_app

    server, requests = server_for({"id": ID, "deleted": True})
    app = create_app(server)

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
            ) as client:
                headers = {
                    "Accept": "application/json, text/event-stream",
                    "X-Request-ID": "agent-test-42",
                }

                async def rpc(method, params):
                    response = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": method,
                            "params": params,
                        },
                    )
                    assert response.status_code == 200
                    return response.json()["result"]

                initialized = await rpc(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                assert initialized["serverInfo"]["name"] == "TripGenie"
                listed = await rpc("tools/list", {})
                assert "activities_delete" in {tool["name"] for tool in listed["tools"]}
                rejected = await rpc(
                    "tools/call",
                    {
                        "name": "activities_delete",
                        "arguments": {"activity_id": ID, "confirm": False},
                    },
                )
                assert rejected["isError"] is True
                assert not requests
                result = await rpc(
                    "tools/call",
                    {
                        "name": "activities_delete",
                        "arguments": {"activity_id": ID, "confirm": True},
                    },
                )
                assert result["structuredContent"]["data"] == {
                    "id": ID,
                    "deleted": True,
                }
                assert result["structuredContent"]["correlation_id"] == "agent-test-42"
                assert requests[0].headers["X-Request-ID"] == "agent-test-42"

    asyncio.run(check())


def test_independent_activity_models_match_public_contract():
    import importlib.util
    from pathlib import Path

    from tripgenie_mcp.activity_models import ActivityFilters, ActivityWrite

    path = (
        Path(__file__).resolve().parents[3]
        / "student-4/backend/student4_backend_service/schemas.py"
    )
    spec = importlib.util.spec_from_file_location("activity_public_contract", path)
    authoritative = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(authoritative)
    authoritative.ActivityWrite.model_rebuild(_types_namespace=vars(authoritative))
    authoritative.ActivityQuery.model_rebuild(_types_namespace=vars(authoritative))
    assert set(ActivityWrite.model_fields) == set(
        authoritative.ActivityWrite.model_fields
    )
    assert set(ActivityFilters.model_fields) == set(
        authoritative.ActivityQuery.model_fields
    ) - {"text", "limit", "offset"}
    assert ActivityWrite.model_validate(WRITE).model_dump(
        mode="json"
    ) == authoritative.ActivityWrite.model_validate(WRITE).model_dump(mode="json")
    for field in ("pricing_basis", "categories", "availability_schedules"):
        assert (
            ActivityWrite.model_json_schema()["properties"][field]
            == authoritative.ActivityWrite.model_json_schema()["properties"][field]
        )


@pytest.mark.parametrize(
    "response",
    [
        DETAIL | {"price": 12.5},
        DETAIL | {"id": "bad"},
        DETAIL | {"pricing_basis": "UNKNOWN"},
    ],
)
def test_activity_reads_reject_invalid_provider_contract(response):
    server, _ = server_for(response)
    result = call(server, "activities_get", {"activity_id": ID})
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    ("status", "code"),
    [(404, "NOT_FOUND"), (422, "VALIDATION_ERROR"), (409, "CONFLICT")],
)
def test_write_known_rejections(status, code):
    server, requests = server_for({"secret": "never expose"}, status)
    result = call(server, "activities_update", {"activity_id": ID, "activity": WRITE})
    assert result["error"]["code"] == code
    assert result["error"]["retryable"] is False
    assert "secret" not in json.dumps(result)
    assert len(requests) == 1


def test_delete_numeric_confirmation_does_not_authorize_write():
    server, requests = server_for({"id": ID, "deleted": True})
    with pytest.raises(ToolError):
        call(server, "activities_delete", {"activity_id": ID, "confirm": 1})
    assert not requests


def test_registered_search_schema_accepts_public_hhmm_times():
    from jsonschema import Draft202012Validator, FormatChecker

    async def scenario():
        server = create_server()
        tools = await server.list_tools()
        tool = next(tool for tool in tools if tool.name == "activities_search")
        validator = Draft202012Validator(
            tool.inputSchema, format_checker=FormatChecker()
        )
        arguments = {
            "filters": {
                "availability": {
                    "date": "2026-10-03",
                    "start_time": "09:00",
                    "end_time": "12:00",
                }
            }
        }
        assert validator.is_valid(arguments), list(validator.iter_errors(arguments))
        arguments["filters"]["availability"]["start_time"] = "09:00:00"
        assert not validator.is_valid(arguments)

    asyncio.run(scenario())


def test_bridge_bound_server_accepts_its_configured_host():
    async def scenario():
        provider = ProviderClient(
            {"student-4": "http://provider.test"},
            httpx.MockTransport(
                lambda request: httpx.Response(200, json={"categories": []})
            ),
        )
        app = create_app(create_server(Settings(host="172.17.0.1"), provider))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://172.17.0.1:8012"
            ) as client:
                response = await client.post(
                    "/mcp",
                    headers={"Accept": "application/json, text/event-stream"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    },
                )
                assert response.status_code == 200, response.text
        provider.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["activities_create", "activities_update"])
def test_oversized_write_is_rejected_before_provider_mutation(name):
    server, requests = server_for(DETAIL, 201 if name == "activities_create" else 200)
    args = {"activity": WRITE | {"description": "x" * 33000}}
    if name == "activities_update":
        args["activity_id"] = ID
    result = call(server, name, args)
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert requests == []


def test_oversized_write_acknowledgement_requires_reconciliation():
    server, requests = server_for(DETAIL | {"description": "x" * 33000}, 201)
    result = call(server, "activities_create", {"activity": WRITE})
    assert len(requests) == 1
    assert result["error"]["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert result["error"]["retryable"] is False
    assert "inspect the catalogue before retrying" in result["error"]["message"]


def test_search_schema_rejects_blank_text_and_accepts_omission():
    from jsonschema import Draft202012Validator

    server, _ = server_for({})
    tool = next(
        t for t in asyncio.run(server.list_tools()) if t.name == "activities_search"
    )
    validator = Draft202012Validator(tool.inputSchema)
    assert not validator.is_valid({"text": ""})
    # Keep whitespace semantics at runtime: a wildcard regex can break Ollama
    # grammar generation by consuming JSON delimiters.
    assert (
        call(server, "activities_search", {"text": "  "})["error"]["code"]
        == "VALIDATION_ERROR"
    )
    assert validator.is_valid({"filters": {"price": {"max": "50.00"}}})
