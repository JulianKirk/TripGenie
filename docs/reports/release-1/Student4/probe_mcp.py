"""Read-only container-to-host MCP probe; does not invoke an LLM."""
import asyncio
import json
from uuid import uuid4

from student4_backend_service.assistant_models import AssistantResponse
from student4_backend_service.assistant_tools import ToolExecutor
from student4_backend_service.config import Settings
from student4_backend_service.mcp_client import connect_mcp


async def main():
    result = AssistantResponse(request_id=f"student4-probe-{uuid4().hex[:16]}")
    async with connect_mcp(Settings.from_env(), result.request_id) as session:
        tools = await session.list_tools()
        executor = ToolExecutor(session, tools.tools, result, None)
        data = await executor.call("activities_list_categories", {})
        print(json.dumps({
            "request_id": result.request_id,
            "result": data,
            "tools": [tool.model_dump(mode="json") for tool in result.tools],
        }, indent=2))
        assert data["ok"] is True


asyncio.run(main())
