"""Feature audiences are advertised without restricting the external catalogue."""

import asyncio

import httpx

from tripgenie_mcp.config import Settings
from tripgenie_mcp.provider import ProviderClient
from tripgenie_mcp.server import CATALOGUE, create_app, create_server

TRIP_TOOLS = {"trip_get_context", "trips_list_itinerary_items"}
EXPECTED_FEATURES = {
    "student-1": TRIP_TOOLS
    | {
        "accommodations_search",
        "transport_search",
        "activities_search",
        "budgets_list",
    },
    "student-2": TRIP_TOOLS
    | {"accommodations_search", "accommodations_get", "accommodations_committed_costs"},
    "student-3": TRIP_TOOLS
    | {
        "transport_search",
        "transport_get",
        "transport_compare",
        "transport_trip_costs",
    },
    "student-4": TRIP_TOOLS
    | {
        "activities_search",
        "activities_create",
        "activities_update",
        "activities_delete",
        "activities_get",
        "activities_list_categories",
        "activities_committed_costs",
    },
    "student-5": TRIP_TOOLS
    | {
        "budgets_list",
        "budgets_get_summary",
        "expenses_list",
        "accommodations_committed_costs",
        "activities_committed_costs",
        "transport_trip_costs",
    },
}


def test_tools_list_advertises_feature_audiences_and_original_owners():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"id": "trip_sydney"}})

    provider = ProviderClient(
        {owner: f"http://{owner}.test" for owner in CATALOGUE},
        httpx.MockTransport(handle),
    )
    app = create_app(create_server(Settings(), provider))

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8012"
            ) as client:

                async def rpc(method, params):
                    response = await client.post(
                        "/mcp",
                        headers={"Accept": "application/json, text/event-stream"},
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": method,
                            "params": params,
                        },
                    )
                    assert response.status_code == 200
                    return response.json()["result"]

                await rpc(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                )
                listed = await rpc("tools/list", {})
                tools = {tool["name"]: tool for tool in listed["tools"]}
                assert tools.keys() == {
                    name for names in CATALOGUE.values() for name in names
                }
                assert not requests
                for owner, names in CATALOGUE.items():
                    for name in names:
                        metadata = tools[name].get("_meta", {}).get("tripgenie")
                        assert metadata is not None, f"Missing feature metadata: {name}"
                        assert metadata == {
                            "owner": owner,
                            "features": sorted(
                                feature
                                for feature, expected in EXPECTED_FEATURES.items()
                                if name in expected
                            ),
                        }
                for feature, expected in EXPECTED_FEATURES.items():
                    assert {
                        name
                        for name, tool in tools.items()
                        if feature in tool["_meta"]["tripgenie"]["features"]
                    } == expected
                writes = {
                    name
                    for name, tool in tools.items()
                    if tool["annotations"]["readOnlyHint"] is False
                }
                assert writes == {
                    "activities_create",
                    "activities_update",
                    "activities_delete",
                }
                for name in writes:
                    assert tools[name]["_meta"]["tripgenie"]["features"] == [
                        "student-4"
                    ]
                result = await rpc(
                    "tools/call",
                    {
                        "name": "trip_get_context",
                        "arguments": {"trip_id": "trip_sydney"},
                    },
                )
                assert result["structuredContent"]["ok"] is True
                assert result["structuredContent"]["source"] == "student-1"
                assert requests[0].url.host == "student-1.test"

    asyncio.run(scenario())
