"""Client for the shared host-run MCP server (Release 1).

Ported from Student 5's client: one JSON-RPC `tools/call` per request against
the server's stateless streamable-HTTP endpoint (it answers with plain JSON).
Every failure -- transport, HTTP, tool error or malformed result -- becomes one
`McpCallError`, so a caller can record it per tool and carry on.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings

MAX_RESULT_BYTES = 32768
PROTOCOL_VERSION = "2025-06-18"


class McpCallError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


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
        """The tool's success envelope: `{ok, data, correlation_id, source}`."""
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
                    # The MCP server reads its correlation id from this header.
                    "X-Request-ID": correlation_id,
                },
            )
        except httpx.TimeoutException as exc:
            raise McpCallError(
                "DEPENDENCY_TIMEOUT", "The MCP tool server timed out.", retryable=True
            ) from exc
        except httpx.RequestError as exc:
            raise McpCallError(
                "DEPENDENCY_UNAVAILABLE",
                "The MCP tool server is unavailable.",
                retryable=True,
            ) from exc

        if response.status_code == 503:
            raise McpCallError(
                "DEPENDENCY_UNAVAILABLE",
                "The MCP tool server is unavailable.",
                retryable=True,
            )
        if response.is_error:
            raise _malformed(f"unexpected HTTP {response.status_code}")
        if len(response.content) > MAX_RESULT_BYTES * 2:
            raise _malformed("tool result exceeds the size limit")

        try:
            result = response.json()["result"]
            structured = result.get("structuredContent")
            is_error = result.get("isError") is True
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise _malformed("response was not a tool result") from exc

        if is_error:
            error = structured.get("error") if isinstance(structured, dict) else None
            if isinstance(error, dict):
                raise McpCallError(
                    str(error.get("code", "MCP_TOOL_ERROR")),
                    str(error.get("message", "The MCP tool failed.")),
                    retryable=error.get("retryable") is True,
                )
            # Argument validation or unknown tool: FastMCP answers in text only.
            raise McpCallError("MCP_TOOL_ERROR", "The MCP tool call was rejected.")

        if (
            not isinstance(structured, dict)
            or structured.get("ok") is not True
            or not isinstance(structured.get("data"), dict)
        ):
            raise _malformed("tool result did not match the envelope")
        if len(json.dumps(structured["data"]).encode()) > MAX_RESULT_BYTES:
            raise _malformed("tool result exceeds 32 KB")
        return structured


def _malformed(issue: str) -> McpCallError:
    return McpCallError(
        "BAD_GATEWAY", f"The MCP tool server returned an invalid response: {issue}."
    )
