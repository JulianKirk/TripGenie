"""The assistant box: a question answered by the model calling MCP tools.

AI-Mode runs the tool loop (it discovers the shared MCP server's catalogue,
which already has the accommodation tools); this service supplies the system
prompt and turns the returned trace into something a page can show -- which
tool ran, with what arguments, and the data it returned. The trace is the
evidence the tools ran; the model's prose alone is not.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend_service.ai_client import AssistError

if TYPE_CHECKING:
    from backend_service.ai_client import AiClient


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=500)


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error", "rejected"] = "error"
    duration_ms: int = 0
    source: str | None = None
    # The tool's own payload: `data` on success, the reason on failure.
    data: Any = None
    error: str | None = None


class AssistantResponse(BaseModel):
    status: Literal["complete", "error", "disabled"]
    request_id: str
    reply: str | None = None
    tools: list[ToolCall] = Field(default_factory=list)
    error: str | None = None


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    return (
        files("backend_service")
        .joinpath("prompts", "accommodation_assistant_v1.md")
        .read_text(encoding="utf-8")
    )


def tool_call(trace: Any) -> ToolCall:
    """One AI-Mode `ToolTrace`, reduced to the MCP envelope's payload.

    ponytail: anything unexpected becomes an error row rather than a failed
    request -- a trace is evidence to show, not a contract to enforce.
    """
    if not isinstance(trace, dict):
        return ToolCall(tool="unknown", error="unreadable tool trace")
    result = trace.get("result") or {}
    envelope = result.get("structuredContent") if isinstance(result, dict) else None
    envelope = envelope if isinstance(envelope, dict) else {}
    failure = envelope.get("error") if isinstance(envelope.get("error"), dict) else {}
    arguments = trace.get("arguments")
    status = trace.get("status")
    return ToolCall(
        tool=str(trace.get("tool") or "unknown"),
        arguments=arguments if isinstance(arguments, dict) else {},
        status=status if status in {"success", "error", "rejected"} else "error",
        duration_ms=int(trace.get("duration_ms") or 0),
        source=envelope.get("source"),
        data=envelope.get("data") if envelope.get("ok") is True else None,
        error=(
            " ".join(
                str(part)
                for part in (failure.get("code"), failure.get("message"))
                if part
            )
            or trace.get("error")
        ),
    )


async def answer(question: str, ai: AiClient) -> AssistantResponse:
    request_id = f"student2-agent-{uuid4().hex[:16]}"
    if not ai.configured:
        return AssistantResponse(
            status="disabled",
            request_id=request_id,
            error=(
                "The accommodation assistant (MCP tools) is switched off here. "
                "Search and everything else on the page still work."
            ),
        )
    try:
        reply, traces = await ai.assist(question, _system_prompt(), request_id)
    except AssistError as exc:
        return AssistantResponse(
            status="error",
            request_id=request_id,
            tools=[tool_call(trace) for trace in exc.tools],
            error=str(exc.detail),
        )
    except HTTPException as exc:
        return AssistantResponse(
            status="error", request_id=request_id, error=str(exc.detail)
        )
    return AssistantResponse(
        status="complete",
        request_id=request_id,
        reply=reply,
        tools=[tool_call(trace) for trace in traces],
    )
