from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import uvicorn

from .ai_mode_client import AiModeClient
from .config import Settings
from .index import RagIndex


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TripGenie shared RAG service")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Run the local RAG HTTP server")
    ingest = commands.add_parser("ingest", help="Build the local RAG index")
    ingest.add_argument("--manifest", type=Path)
    ingest.add_argument(
        "--rebuild",
        action="store_true",
        help="Accepted for an explicit full index build; rebuilds are always atomic.",
    )
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    settings = Settings.from_env()
    if arguments.command == "serve":
        uvicorn.run(
            "rag_service.app:app",
            host=settings.bind_host,
            port=settings.port,
        )
        return
    if arguments.manifest:
        settings = replace(settings, manifest_path=arguments.manifest.resolve())
    summary = asyncio.run(_ingest(settings))
    print(json.dumps(summary, indent=2, sort_keys=True))


async def _ingest(settings: Settings) -> dict[str, object]:
    client = AiModeClient(settings)
    started = perf_counter()
    try:
        result = await RagIndex(settings).rebuild(client)
        summary = result.model_dump(mode="json")
        summary["duration_ms"] = round((perf_counter() - started) * 1000)
        return summary
    finally:
        await client.close()
