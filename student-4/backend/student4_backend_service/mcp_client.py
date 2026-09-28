"""Request-scoped MCP SDK connection; callers cannot select upstream URLs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .config import Settings


@asynccontextmanager
async def connect_mcp(
    settings: Settings,
    request_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[ClientSession]:
    async with (
        httpx.AsyncClient(
            headers={"X-Request-ID": request_id},
            timeout=httpx.Timeout(settings.mcp_timeout),
            transport=transport,
            follow_redirects=False,
        ) as client,
        streamable_http_client(settings.mcp_url, http_client=client) as (
            read,
            write,
            _,
        ),
        ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=settings.mcp_timeout)
        ) as session,
    ):
        await session.initialize()
        yield session
