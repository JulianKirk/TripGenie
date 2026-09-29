"""Shared native tool-call loop. MCP owns tools; the model owns interpretation."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from time import monotonic
from typing import Any

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import GenerateRequest, ToolTrace
from .provider import OllamaProviderAdapter
from .schema import validate_schema


def _failure(exc: BaseException) -> ApiError:
    if isinstance(exc, BaseExceptionGroup):
        return _failure(exc.exceptions[0])
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return dependency_timeout("The generation agent timed out.")
    return dependency_unavailable(
        "The MCP service is unavailable or returned an invalid response."
    )


class Agent:
    def __init__(
        self,
        provider: OllamaProviderAdapter,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.provider = provider
        self.settings = settings
        self.transport = transport

    async def generate(
        self, payload: GenerateRequest, model: str, request_id: str
    ) -> tuple[str, list[ToolTrace]]:
        trace: list[ToolTrace] = []
        try:
            async with (
                asyncio.timeout(self.settings.agent_timeout_seconds),
                httpx.AsyncClient(
                    headers={"X-Request-ID": request_id},
                    timeout=self.settings.mcp_timeout_seconds,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client,
                streamable_http_client(self.settings.mcp_url, http_client=client) as (
                    read,
                    write,
                    _,
                ),
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(
                        seconds=self.settings.mcp_timeout_seconds
                    ),
                ) as session,
            ):
                await session.initialize()
                answer = await self._run(session, payload, model, request_id, trace)
            return answer, trace
        except Exception as exc:
            error = _failure(exc)
            error.tools = [entry.model_dump(mode="json") for entry in trace]
            raise error from exc

    def _bound(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> None:
        if (
            len(json.dumps([messages, tools], ensure_ascii=False))
            > self.settings.agent_context_chars
        ):
            raise bad_gateway(
                "The agent context exceeds its configured limit. "
                "Please narrow the request."
            )

    async def _run(
        self,
        session: ClientSession,
        payload: GenerateRequest,
        model: str,
        request_id: str,
        trace: list[ToolTrace],
    ) -> str:
        catalogue = {}
        cursor = None
        cursors = set()
        while True:
            page = await session.list_tools(cursor=cursor)
            for tool in page.tools:
                if tool.name in catalogue:
                    raise bad_gateway("MCP advertised duplicate tool names.")
                validate_schema(tool.inputSchema)
                catalogue[tool.name] = tool
            self._bound(
                [], [tool.model_dump(mode="json") for tool in catalogue.values()]
            )
            cursor = page.nextCursor
            if not cursor:
                break
            if cursor in cursors:
                raise bad_gateway("MCP tool discovery repeated a page.")
            cursors.add(cursor)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in catalogue.values()
        ]
        messages = []
        if payload.system:
            messages.append({"role": "system", "content": payload.system})
        messages.append({"role": "user", "content": payload.prompt})
        executed: set[str] = set()
        for _ in range(self.settings.agent_max_turns):
            self._bound(messages, tools)
            reply = await self.provider.chat(
                model=model,
                messages=messages,
                tools=tools,
                schema=payload.output_schema if not tools else None,
            )
            messages.append(reply.model_dump(mode="json", exclude_none=True))
            if not reply.tool_calls:
                # Schema-constrained formatting is a model call, not authored prose or
                # domain logic. Keep native tool selection separate from JSON grammar.
                if payload.output_schema is not None and tools:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Return the final answer as the requested JSON, "
                            "using the conversation and tool results. "
                            "Recheck the draft against the original user request "
                            "and system instructions. Correct unsupported claims "
                            "or mismatches. If essential information is missing, "
                            "ask the user for it instead of assuming it. "
                            "Do not call more tools or invent missing facts.",
                        }
                    )
                    self._bound(messages, [])
                    reply = await self.provider.chat(
                        model=model,
                        messages=messages,
                        tools=[],
                        schema=payload.output_schema,
                    )
                    if reply.tool_calls:
                        raise bad_gateway(
                            "The model requested tools during final answer formatting."
                        )
                text = reply.content or ""
                if not text.strip():
                    raise bad_gateway("The model returned an empty final answer.")
                if payload.output_schema is not None:
                    try:
                        Draft202012Validator(payload.output_schema).validate(
                            json.loads(text)
                        )
                    except (ValueError, ValidationError, SchemaError) as exc:
                        raise bad_gateway(
                            "The model returned an invalid structured answer."
                        ) from exc
                return text
            for call in reply.tool_calls:
                name, arguments = call.function.name, call.function.arguments
                entry = ToolTrace(tool=name, arguments=arguments)
                trace.append(entry)
                tool = catalogue.get(name)
                signature = json.dumps([name, arguments], sort_keys=True)
                if (
                    tool is None
                    or not Draft202012Validator(
                        tool.inputSchema, format_checker=FormatChecker()
                    ).is_valid(arguments)
                    or (
                        signature in executed
                        and not (tool.annotations and tool.annotations.readOnlyHint)
                    )
                    or len(trace) > self.settings.agent_max_calls
                ):
                    entry.status, entry.error = (
                        "rejected",
                        "INVALID_OR_REPEATED_TOOL_CALL",
                    )
                    raise bad_gateway(
                        "The model requested an invalid, repeated "
                        "or excessive tool call."
                    )
                executed.add(signature)
                start = monotonic()
                try:
                    result = await session.call_tool(
                        name, arguments, meta={"request_id": request_id}
                    )
                    data = result.model_dump(mode="json", exclude_none=True)
                    encoded = json.dumps(data, ensure_ascii=False)
                    failed = result.isError or (
                        isinstance(result.structuredContent, dict)
                        and result.structuredContent.get("ok") is False
                    )
                    entry.status = "error" if failed else "success"
                    entry.error = "TOOL_ERROR" if failed else None
                    if len(encoded.encode("utf-8")) > self.settings.agent_result_bytes:
                        entry.error = "RESULT_TOO_LARGE"
                        raise bad_gateway(
                            "MCP completed a call but its result exceeds "
                            "the configured limit."
                        )
                    entry.result = data
                    messages.append(
                        {"role": "tool", "tool_name": name, "content": encoded}
                    )
                finally:
                    entry.duration_ms = round((monotonic() - start) * 1000)
                    if entry.status == "error" and not entry.error:
                        entry.error = "INVALID_OR_UNAVAILABLE_RESULT"
        raise bad_gateway("The generation agent reached its tool-turn limit.")
