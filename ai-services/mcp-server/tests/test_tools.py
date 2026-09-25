import asyncio
from uuid import uuid4

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from tripgenie_mcp.config import Settings
from tripgenie_mcp.provider import ProviderClient
from tripgenie_mcp.server import CATALOGUE, create_app, create_server
from tripgenie_mcp.tools import DomainTools

TRIP = "trip_2026_sydney"
TRANSPORT = "transport_2026_bus"
UUID = "5ad9845c-a7d1-5688-b06a-63e92bed4345"
URLS = {name: f"http://{name}.test" for name in CATALOGUE}


def fixture(response, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return httpx.Response(status, json=response)

    return DomainTools(ProviderClient(URLS, httpx.MockTransport(handler))), requests


@pytest.mark.parametrize(
    ("owner", "action", "args", "response", "method", "path"),
    [
        (
            "student-1",
            "trip_get_context",
            (TRIP,),
            {"data": {"id": TRIP}},
            "GET",
            f"/api/trips/{TRIP}",
        ),
        (
            "student-1",
            "trips_list_itinerary_items",
            (TRIP,),
            {"data": [{"id": "item_one"}]},
            "GET",
            f"/api/trips/{TRIP}/itinerary-items",
        ),
        (
            "student-2",
            "accommodations_search",
            ("australia", "sydney"),
            {"accommodations": [{"id": UUID, "price_per_night": 12.5}], "total": 1},
            "QUERY",
            "/accommodation",
        ),
        (
            "student-2",
            "accommodations_get",
            (UUID,),
            {"id": UUID, "price_per_night": 12.5},
            "GET",
            f"/accommodation/{UUID}",
        ),
        (
            "student-2",
            "accommodations_committed_costs",
            (TRIP,),
            {"committed_cost_total": "2.00", "currency": "AUD", "items": []},
            "GET",
            f"/accommodation/trips/{TRIP}/committed-costs",
        ),
        (
            "student-3",
            "transport_search",
            ("Sydney", "Canberra"),
            {
                "data": [
                    {
                        "id": TRANSPORT,
                        "price": 12.5,
                        "pricing_basis": "PER_TRAVELLER",
                        "seats_remaining": None,
                    }
                ]
            },
            "GET",
            "/api/transport-options",
        ),
        (
            "student-3",
            "transport_get",
            (TRANSPORT,),
            {
                "data": {
                    "id": TRANSPORT,
                    "price": 12.5,
                    "pricing_basis": "PER_TRAVELLER",
                    "seats_remaining": None,
                }
            },
            "GET",
            f"/api/transport-options/{TRANSPORT}",
        ),
        (
            "student-3",
            "transport_compare",
            ([TRANSPORT],),
            {
                "data": [
                    {"id": TRANSPORT, "price": 12.5, "pricing_basis": "PER_TRAVELLER"}
                ]
            },
            "GET",
            "/api/transport-options/compare",
        ),
        (
            "student-3",
            "transport_trip_costs",
            (TRIP,),
            {
                "data": {
                    "trip_id": TRIP,
                    "currency": "AUD",
                    "entry_count": 0,
                    "active_entry_count": 0,
                    "estimated_cost_total": 0.0,
                    "planned": [],
                }
            },
            "GET",
            f"/api/trips/{TRIP}/transport",
        ),
        (
            "student-4",
            "activities_search",
            ("harbour",),
            {
                "activities": [
                    {
                        "id": UUID,
                        "price": "45.00",
                        "pricing_basis": "PER_PERSON",
                        "maximum_participants": None,
                    }
                ],
                "total": 1,
            },
            "QUERY",
            "/activity",
        ),
        (
            "student-4",
            "activities_get",
            (UUID,),
            {"id": UUID, "price": "45.00", "pricing_basis": "FLAT_ADMISSION"},
            "GET",
            f"/activity/{UUID}",
        ),
        (
            "student-4",
            "activities_list_categories",
            (),
            {"categories": [{"code": "OUTDOOR"}]},
            "GET",
            "/activity/categories",
        ),
        (
            "student-4",
            "activities_committed_costs",
            (TRIP,),
            {"committed_cost_total": "45.00", "currency": "AUD", "items": []},
            "GET",
            f"/activity/trips/{TRIP}/committed-costs",
        ),
        (
            "student-5",
            "budgets_list",
            (),
            {
                "data": [
                    {
                        "budget_id": UUID,
                        "trip_id": TRIP,
                        "currency": "AUD",
                        "total_budget": "500.00",
                    }
                ]
            },
            "GET",
            "/api/v1/budgets",
        ),
        (
            "student-5",
            "budgets_get_summary",
            (UUID,),
            {
                "data": {
                    "budget_id": UUID,
                    "trip_id": TRIP,
                    "currency": "AUD",
                    "total_budget": "500.00",
                    "actual_spending": "20.00",
                    "committed_costs": "10.00",
                    "remaining_budget": "10.00",
                    "category_totals": {"food": "20.00"},
                    "actual_spending_complete": False,
                    "committed_costs_complete": False,
                    "remaining_budget_complete": False,
                    "unconverted_expense_count": 1,
                    "providers": {
                        "student-2": {"status": "unavailable", "subtotal": None}
                    },
                }
            },
            "GET",
            f"/api/v1/budgets/{UUID}/summary",
        ),
        (
            "student-5",
            "expenses_list",
            (TRIP,),
            {
                "data": [
                    {
                        "expense_id": UUID,
                        "trip_id": TRIP,
                        "category": "food",
                        "description": "Lunch",
                        "amount": "12.00",
                        "currency": "AUD",
                        "date": "2026-09-26",
                        "notes": "private",
                        "payment_method": "private",
                    }
                ]
            },
            "GET",
            "/api/v1/expenses",
        ),
    ],
)
def test_registered_tool_reads_only_public_api(
    owner, action, args, response, method, path
):
    tools, requests = fixture(response)
    result = tools.execute(owner, lambda: getattr(tools, action)(*args))
    assert result["ok"] is True
    assert result["source"] == owner
    assert result["correlation_id"].startswith("mcp-")
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == path
    if action == "expenses_list":
        assert "notes" not in str(result["data"])
        assert "payment_method" not in str(result["data"])
    if action == "budgets_get_summary":
        assert result["data"]["providers"]["student-2"]["subtotal"] is None
    if action == "transport_get":
        assert result["data"]["seats_remaining"] is None
    if action == "activities_get":
        assert result["data"]["pricing_basis"] == "FLAT_ADMISSION"


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("trip_get_context", ("../other",)),
        ("transport_get", ("not_transport",)),
        ("transport_compare", ([TRANSPORT] * 5,)),
        ("accommodations_get", ("invalid",)),
        ("activities_get", ("invalid",)),
        ("accommodations_search", (None, "Sydney")),
        ("activities_search", ("",)),
        ("budgets_list", (None, 51)),
        ("budgets_get_summary", ("invalid",)),
        ("expenses_list", (TRIP, "invalid")),
        ("expenses_list", (TRIP, None, "2026-02-30")),
    ],
)
def test_invalid_input_never_calls_provider(action, args):
    tools, requests = fixture({"data": []})
    result = tools.execute("student-5", lambda: getattr(tools, action)(*args))
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert not requests


@pytest.mark.parametrize(
    ("response", "status", "code", "retryable"),
    [
        ({"detail": "secret"}, 404, "NOT_FOUND", False),
        ({"detail": "secret"}, 422, "VALIDATION_ERROR", False),
        ({"detail": "secret"}, 503, "PROVIDER_UNAVAILABLE", True),
        ({"bad": []}, 200, "INVALID_RESPONSE", False),
        (httpx.ConnectError("private"), 200, "PROVIDER_UNAVAILABLE", True),
        (httpx.ReadTimeout("private"), 200, "PROVIDER_TIMEOUT", True),
    ],
)
def test_provider_errors_are_structured_and_safe(response, status, code, retryable):
    tools, requests = fixture(response, status)
    result = tools.execute("student-5", lambda: tools.budgets_list())
    assert result["error"]["code"] == code
    assert result["error"]["retryable"] is retryable
    assert "secret" not in str(result)
    assert len(requests) == 1


def test_malformed_ids_money_and_unavailable_are_not_success():
    for response, action, args in [
        ({"data": [{"no_id": "x"}]}, "transport_search", ()),
        (
            {
                "data": {
                    "id": TRANSPORT,
                    "price": "NaN",
                    "pricing_basis": "PER_TRAVELLER",
                }
            },
            "transport_get",
            (TRANSPORT,),
        ),
        (
            {
                "data": {
                    "budget_id": UUID,
                    "currency": "AUD",
                    "remaining_budget": "0.00",
                    "actual_spending_complete": True,
                    "committed_costs_complete": False,
                    "remaining_budget_complete": False,
                    "unconverted_expense_count": 0,
                    "providers": {
                        "student-2": {"status": "unavailable", "subtotal": "0.00"}
                    },
                }
            },
            "budgets_get_summary",
            (UUID,),
        ),
    ]:
        tools, _ = fixture(response)
        result = tools.execute(
            "student-5",
            lambda tools=tools, action=action, args=args: getattr(tools, action)(*args),
        )
        assert result["error"]["code"] == "INVALID_RESPONSE"


def test_response_size_and_provenance():
    tools, _ = fixture({"data": {"id": "invented", "extra": "x" * 40000}})
    result = tools.execute("student-1", lambda: tools.trip_get_context(TRIP))
    assert result["error"]["code"] == "INVALID_RESPONSE"
    tools, _ = fixture(
        {"data": [{"id": "invented", "price": 1, "pricing_basis": "PER_TRAVELLER"}]}
    )
    result = tools.execute("student-3", lambda: tools.transport_compare([TRANSPORT]))
    assert result["error"]["code"] == "INVALID_RESPONSE"
    tools, _ = fixture({"activities": [{"id": "invented"}], "total": 1})
    result = tools.execute("student-4", lambda: tools.activities_search())
    assert result["error"]["code"] == "INVALID_RESPONSE"
    tools, _ = fixture({"id": str(uuid4()), "price_per_night": 12.5})
    result = tools.execute("student-2", lambda: tools.accommodations_get(UUID))
    assert result["error"]["code"] == "INVALID_RESPONSE"


def test_transport_costs_preserve_basis_and_normalize_nested_money():
    payload = {
        "trip_id": TRIP,
        "currency": "AUD",
        "entry_count": 1,
        "active_entry_count": 1,
        "estimated_cost_total": 25.0,
        "planned": [
            {
                "estimated_cost": 25.0,
                "entry": {"transport_id": TRANSPORT},
                "option": {
                    "id": TRANSPORT,
                    "price": 12.5,
                    "pricing_basis": "PER_TRAVELLER",
                    "seats_remaining": None,
                },
            }
        ],
    }
    tools, _ = fixture({"data": payload})
    result = tools.execute("student-3", lambda: tools.transport_trip_costs(TRIP))
    assert result["data"]["estimated_cost_total"] == "25.00"
    assert result["data"]["planned"][0]["estimated_cost"] == "25.00"
    assert result["data"]["planned"][0]["option"]["price"] == "12.50"
    assert result["data"]["planned"][0]["option"]["seats_remaining"] is None


def test_budget_summary_rejects_missing_or_inexact_totals():
    base = {
        "budget_id": UUID,
        "trip_id": TRIP,
        "currency": "AUD",
        "total_budget": "500.00",
        "actual_spending": "20.00",
        "actual_spending_complete": True,
        "committed_costs": "10.00",
        "committed_costs_complete": True,
        "remaining_budget": "470.00",
        "remaining_budget_complete": True,
        "unconverted_expense_count": 0,
        "category_totals": {"food": "20.00"},
        "providers": {"student-2": {"status": "available", "subtotal": "10.00"}},
    }
    for change in ({"total_budget": None}, {"total_budget": "500.1"}):
        tools, _ = fixture({"data": base | change})
        result = tools.execute(
            "student-5", lambda tools=tools: tools.budgets_get_summary(UUID)
        )
        assert result["error"]["code"] == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    ("response", "action", "args"),
    [
        (
            {
                "data": [
                    {
                        "budget_id": UUID,
                        "trip_id": TRIP,
                        "currency": "AUD",
                        "total_budget": 1.5,
                    }
                ]
            },
            "budgets_list",
            (),
        ),
        (
            {
                "data": [
                    {
                        "expense_id": UUID,
                        "trip_id": TRIP,
                        "category": "food",
                        "description": "Lunch",
                        "amount": 1.5,
                        "currency": "AUD",
                        "date": "2026-09-26",
                    }
                ]
            },
            "expenses_list",
            (TRIP,),
        ),
        (
            {"committed_cost_total": 1.5, "currency": "AUD", "items": []},
            "activities_committed_costs",
            (TRIP,),
        ),
    ],
)
def test_exact_provider_money_contract(response, action, args):
    tools, _ = fixture(response)
    result = tools.execute("student-5", lambda: getattr(tools, action)(*args))
    assert result["error"]["code"] == "INVALID_RESPONSE"


@pytest.mark.parametrize(
    ("owner", "action", "args", "response"),
    [
        ("student-1", "trips_list_itinerary_items", (TRIP,), {"data": []}),
        ("student-2", "accommodations_search", (), {"accommodations": [], "total": 0}),
        ("student-3", "transport_search", (), {"data": []}),
        ("student-4", "activities_search", (), {"activities": [], "total": 0}),
        ("student-5", "budgets_list", (), {"data": []}),
        ("student-5", "expenses_list", (TRIP,), {"data": []}),
    ],
)
def test_empty_discovery_results(owner, action, args, response):
    tools, _ = fixture(response)
    result = tools.execute(owner, lambda: getattr(tools, action)(*args))
    assert result["ok"] is True
    assert result["data"]["count"] == 0
    assert result["data"]["truncated"] is False


def test_bounded_discovery_is_marked_truncated():
    item = {
        "budget_id": UUID,
        "trip_id": TRIP,
        "currency": "AUD",
        "total_budget": "10.00",
    }
    tools, _ = fixture({"data": [item, item]})
    result = tools.execute("student-5", lambda: tools.budgets_list(limit=1))
    assert result["data"]["count"] == 1
    assert result["data"]["truncated"] is True


def test_sdk_lists_tools_and_rejects_unknown_names():
    tools, requests = fixture({"data": {"id": TRIP}})
    server = create_server(Settings(urls=URLS), tools.provider)
    listed = asyncio.run(server.list_tools())
    assert {tool.name for tool in listed} == {
        name for names in CATALOGUE.values() for name in names
    }
    assert all(tool.inputSchema["type"] == "object" for tool in listed)
    result = asyncio.run(server.call_tool("trip_get_context", {"trip_id": TRIP}))
    assert result[1]["ok"] is True
    assert len(requests) == 1
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("budgets_delete", {"budget_id": str(uuid4())}))
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("budgets_list", {"unknown_filter": "ignored"}))
    assert len(requests) == 1
    error = asyncio.run(server.call_tool("budgets_get_summary", {"budget_id": "bad"}))
    assert error.isError is True
    assert error.structuredContent["error"]["code"] == "VALIDATION_ERROR"


def test_diagnostics_do_not_probe_providers():
    tools, requests = fixture({"data": []})
    app = create_app(create_server(Settings(urls=URLS), tools.provider))

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            assert (await client.get("/health")).json()["status"] == "healthy"
            assert (await client.get("/ready")).json()["providers"] == "not_probed"

    asyncio.run(check())
    assert not requests
