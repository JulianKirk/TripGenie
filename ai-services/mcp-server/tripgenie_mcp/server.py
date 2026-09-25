"""Shared host-run MCP server for read-only student tools."""

import json
from functools import wraps
from inspect import signature
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from starlette.responses import JSONResponse
from starlette.routing import Route

from .config import Settings
from .provider import ProviderClient
from .tools import DomainTools

CATALOGUE = {
    "student-1": {
        "trip_get_context": "Read one trip's public context.",
        "trips_list_itinerary_items": "List bounded itinerary items for a trip.",
    },
    "student-2": {
        "accommodations_search": "Discover accommodation IDs using location filters.",
        "accommodations_get": "Read an accommodation by UUID.",
        "accommodations_committed_costs": "Read committed stay costs for a trip.",
    },
    "student-3": {
        "transport_search": "Discover transport IDs using route filters.",
        "transport_get": "Read transport with its pricing basis and unknown capacity.",
        "transport_compare": "Compare up to four discovered transport IDs.",
        "transport_trip_costs": "Read a trip's priced transport selections.",
    },
    "student-4": {
        "activities_search": "Discover activities using optional text search.",
        "activities_get": "Read an activity with exact price and pricing basis.",
        "activities_list_categories": "Read public activity category codes.",
        "activities_committed_costs": "Read committed activity costs for a trip.",
    },
    "student-5": {
        "budgets_list": "List bounded public budgets, optionally by trip.",
        "budgets_get_summary": "Read a budget summary with provider availability.",
        "expenses_list": "List bounded expenses without notes or payment details.",
    },
}


def create_server(
    settings: Settings | None = None, provider: ProviderClient | None = None
) -> FastMCP:
    settings = settings or Settings.from_env()
    provider = provider or ProviderClient(settings.urls)
    tools = DomainTools(provider)
    server = FastMCP(
        "TripGenie",
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "localhost:*", "host.docker.internal:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    def wrap(action, owner):
        @wraps(action)
        def call(**kwargs):
            result = tools.execute(owner, lambda: action(**kwargs))
            if not result["ok"]:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result))],
                    structuredContent=result,
                    isError=True,
                )
            return result

        call.__signature__ = signature(action).replace(return_annotation=dict[str, Any])
        return call

    for owner, names in CATALOGUE.items():
        for name, description in names.items():
            server.add_tool(
                wrap(getattr(tools, name), owner),
                name=name,
                description=description,
                structured_output=True,
            )
            registered = server._tool_manager.get_tool(name)
            registered.fn_metadata.arg_model.model_config["extra"] = "forbid"
            registered.fn_metadata.arg_model.model_rebuild(force=True)
            registered.parameters["additionalProperties"] = False
    return server


def create_app(server: FastMCP | None = None):
    server = server or create_server()
    app = server.streamable_http_app()

    async def health(request):
        return JSONResponse({"status": "healthy", "service": "tripgenie-mcp"})

    async def ready(request):
        return JSONResponse(
            {"status": "ready", "service": "tripgenie-mcp", "providers": "not_probed"}
        )

    app.routes.extend([Route("/health", health), Route("/ready", ready)])
    return app


app = create_app()
