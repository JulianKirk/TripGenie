from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_error

MAX_RESULT_BYTES = 32768
PROTOCOL_VERSION = "2025-06-18"


class McpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = settings.mcp_base_url
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.mcp_timeout_seconds, connect=3.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def call_tool(
        self, name: str, arguments: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        try:
            response = self._client.post(
                self._url,
                json={
                    "jsonrpc": "2.0",
                    "id": correlation_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": PROTOCOL_VERSION,
                },
            )
        except httpx.TimeoutException as exc:
            raise ApiError(
                504,
                "DEPENDENCY_TIMEOUT",
                "The MCP tool server timed out.",
                [{"field": "mcp", "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_error("mcp", "connection failed") from exc

        if response.status_code == 503:
            raise dependency_error("mcp", "server unavailable")
        if response.is_error:
            raise bad_gateway("mcp", f"unexpected HTTP {response.status_code}")

        try:
            result = response.json()["result"]
            structured = result.get("structuredContent")
            is_error = result.get("isError") is True
            text = " ".join(
                str(item.get("text", "")) for item in result.get("content", [])
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise bad_gateway("mcp", "response was not a tool result") from exc

        if is_error:
            if isinstance(structured, dict) and isinstance(
                structured.get("error"), dict
            ):
                error = structured["error"]
                raise ApiError(
                    502,
                    "MCP_TOOL_ERROR",
                    str(error.get("message", "The MCP tool failed.")),
                    [{"field": "mcp", "issue": str(error.get("code", "TOOL_ERROR"))}],
                )
            if "Unknown tool" in text:
                raise dependency_error("mcp", "tool not registered")
            raise bad_gateway("mcp", "tool call failed")

        if (
            not isinstance(structured, dict)
            or structured.get("ok") is not True
            or not isinstance(structured.get("data"), dict)
        ):
            raise bad_gateway("mcp", "tool result did not match the envelope")
        data: dict[str, Any] = structured["data"]
        if len(json.dumps(data).encode()) > MAX_RESULT_BYTES:
            raise bad_gateway("mcp", "tool result exceeds 32 KB")
        return data
