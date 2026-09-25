"""Start the host server or inspect and call it through the MCP protocol."""

import argparse
import asyncio
import json

import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import Settings


async def inspect_or_call(command: str, url: str, name: str, arguments: str) -> None:
    async with streamable_http_client(url) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            if command == "inspect":
                output = (await session.list_tools()).model_dump(mode="json")
            else:
                output = (
                    await session.call_tool(name, json.loads(arguments))
                ).model_dump(mode="json")
            print(json.dumps(output, indent=2))


def main() -> None:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="TripGenie shared MCP server")
    parser.add_argument("command", choices=("serve", "inspect", "call"))
    parser.add_argument("name", nargs="?", help="Registered tool name for call")
    parser.add_argument(
        "arguments", nargs="?", default="{}", help="JSON tool arguments"
    )
    parser.add_argument("--url", default=f"http://127.0.0.1:{settings.port}/mcp")
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("tripgenie_mcp.server:app", host=settings.host, port=settings.port)
    else:
        if args.command == "call" and not args.name:
            parser.error("call requires a registered tool name")
        asyncio.run(inspect_or_call(args.command, args.url, args.name, args.arguments))


if __name__ == "__main__":
    main()
