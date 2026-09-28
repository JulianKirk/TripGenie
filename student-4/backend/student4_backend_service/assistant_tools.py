"""The execution policy and factual provenance live here, outside model control."""

from __future__ import annotations

import json
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from .assistant_models import AssistantResponse, ToolTrace
from .schemas import Activity, ActivitySummary

if TYPE_CHECKING:
    from mcp import ClientSession
    from mcp.types import Tool

READ_TOOLS = frozenset(
    {
        "activities_search",
        "activities_get",
        "activities_list_categories",
        "activities_committed_costs",
        "trip_get_context",
        "trips_list_itinerary_items",
    }
)
TRIP_TOOLS = frozenset(
    {"activities_committed_costs", "trip_get_context", "trips_list_itinerary_items"}
)
LOGGER = logging.getLogger(__name__)


class AgentError(Exception):
    """Safe, user-visible failure message."""


class ToolExecutor:
    def __init__(
        self,
        session: ClientSession,
        tools: list[Tool],
        result: AssistantResponse,
        trip_id: str | None,
    ) -> None:
        self.session = session
        self.tools = {
            tool.name: tool
            for tool in tools
            if tool.name in READ_TOOLS
            and (trip_id is not None or tool.name not in TRIP_TOOLS)
        }
        self.result = result
        self.trip_id = trip_id
        self.known_ids: set[str] = set()

    def _check(self, name: str, arguments: dict[str, Any]) -> None:
        if name not in READ_TOOLS or name not in self.tools:
            message = "The assistant requested a tool that is not allowed."
            raise AgentError(message)
        if name in TRIP_TOOLS and (
            self.trip_id is None or arguments.get("trip_id") != self.trip_id
        ):
            message = "Trip tools can only read the explicitly selected trip."
            raise AgentError(message)
        validator = Draft202012Validator(
            self.tools[name].inputSchema, format_checker=FormatChecker()
        )
        if not validator.is_valid(arguments):
            message = "The assistant supplied invalid tool arguments."
            raise AgentError(message)
        if name == "activities_search":
            filters = arguments.get("filters") or {}
            if not isinstance(filters, dict) or filters.get("include_inactive"):
                message = "The assistant may only search active activities."
                raise AgentError(message)

    def _facts(
        self, name: str, arguments: dict[str, Any], data: dict[str, Any]
    ) -> list[str]:
        if name == "activities_get":
            activity = Activity.model_validate(data)
            if str(activity.id) != arguments.get("activity_id"):
                message = "MCP returned a different activity than requested."
                raise AgentError(message)
            return [str(activity.id)]
        if name == "activities_search":
            rows = data.get("items")
            if not isinstance(rows, list) or len(rows) > 50:
                message = "MCP returned invalid activity search results."
                raise AgentError(message)
            ids = []
            for row in rows:
                if not isinstance(row, dict):
                    message = "MCP returned invalid activity search results."
                    raise AgentError(message)
                fields = {
                    key: value
                    for key, value in row.items()
                    if key in ActivitySummary.model_fields
                }
                ids.append(str(ActivitySummary.model_validate(fields).id))
            return ids
        if name == "trip_get_context" and data.get("id") != arguments.get("trip_id"):
            message = "MCP returned a different trip than requested."
            raise AgentError(message)
        return []

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        start = monotonic()
        trace = ToolTrace(tool=name, arguments=arguments, status="error", duration_ms=0)
        self.result.tools.append(trace)
        try:
            self._check(name, arguments)
        except AgentError:
            trace.status = "rejected"
            trace.error = "POLICY_REJECTED"
            raise
        try:
            response = await self.session.call_tool(
                name, arguments, meta={"request_id": self.result.request_id}
            )
            # SDK argument validation errors legitimately have text content only.
            # They carry no factual provenance and cannot authorize activity IDs.
            if response.isError and response.structuredContent is None:
                trace.error = "TOOL_ERROR"
                detail = " ".join(
                    item.text[:1000] for item in response.content if item.type == "text"
                )[:1000]
                return {"ok": False, "error": trace.error, "detail": detail}
            envelope = response.structuredContent
            if not isinstance(envelope, dict) or len(json.dumps(envelope)) > 32768:
                message = "MCP returned an invalid or oversized tool result."
                raise AgentError(message)
            expected_source = (
                "student-1" if name.startswith(("trip_", "trips_")) else "student-4"
            )
            if envelope.get("source") != expected_source or not isinstance(
                envelope.get("correlation_id"), str
            ):
                message = "MCP returned invalid tool provenance."
                raise AgentError(message)
            trace.correlation_id = envelope["correlation_id"]
            if response.isError or envelope.get("ok") is False:
                error = envelope.get("error", {})
                trace.error = (
                    str(error.get("code", "TOOL_ERROR"))[:80]
                    if isinstance(error, dict)
                    else "TOOL_ERROR"
                )
                detail = (
                    str(error.get("message", ""))[:1000]
                    if isinstance(error, dict)
                    else ""
                )
                return {"ok": False, "error": trace.error, "detail": detail}
            data = envelope.get("data")
            if envelope.get("ok") is not True or not isinstance(data, dict):
                message = "MCP returned a malformed successful result."
                raise AgentError(message)
            trace.activity_ids = self._facts(name, arguments, data)
            self.known_ids.update(trace.activity_ids)
            trace.result_count = (
                len(trace.activity_ids)
                if name in {"activities_get", "activities_search"}
                else None
            )
            trace.status = "success"
            return {"ok": True, "data": data}
        except ValidationError as exc:
            message = "MCP returned invalid activity data."
            raise AgentError(message) from exc
        finally:
            trace.duration_ms = round((monotonic() - start) * 1000)
            if trace.status == "error" and trace.error is None:
                trace.error = "INVALID_OR_UNAVAILABLE_RESULT"
            LOGGER.info(
                "MCP request=%s tool=%s status=%s correlation=%s duration_ms=%s",
                self.result.request_id,
                name,
                trace.status,
                trace.correlation_id,
                trace.duration_ms,
            )
