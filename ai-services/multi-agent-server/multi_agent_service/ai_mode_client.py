"""The Multi-Agent Server's only route to a model: the shared AI-Mode gateway.

AI-Mode stays the sole Ollama adapter. The Planner and Reviewer use the
tool-free `/generate-plain` (the Planner with `tool_catalogue`, so AI-Mode
describes the MCP tools without executing any); the Worker uses `/generate`,
where AI-Mode runs the model-directed MCP tool loop and returns the real tool
trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from .errors import AgentError

if TYPE_CHECKING:
    from .config import Settings


@dataclass(slots=True)
class Generation:
    response: str
    ai_run_id: str
    model: str
    tools: list[dict[str, Any]] = field(default_factory=list)


class AiModeError(AgentError):
    """An AI-Mode failure, carrying any tool calls that already ran."""

    def __init__(
        self,
        code: str,
        message: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(code, message)
        self.tools = tools or []


def _unavailable() -> AiModeError:
    message = "AI-Mode is unavailable."
    return AiModeError("DEPENDENCY_UNAVAILABLE", message)


def _timeout() -> AiModeError:
    message = "AI-Mode timed out."
    return AiModeError("DEPENDENCY_TIMEOUT", message)


def _malformed(what: str) -> AiModeError:
    message = f"AI-Mode returned a malformed {what}."
    return AiModeError("BAD_GATEWAY", message)


class AiModeClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = settings.model
        self._client = httpx.AsyncClient(
            base_url=settings.ai_mode_base_url,
            timeout=httpx.Timeout(60.0, connect=3.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/health", timeout=3.0)
        except httpx.RequestError as exc:
            raise _unavailable() from exc
        if response.is_error:
            raise _unavailable()
        try:
            return dict(response.json()["data"])
        except (ValueError, KeyError, TypeError) as exc:
            raise _malformed(what="health response") from exc

    async def generate(
        self,
        *,
        prompt: str,
        system: str,
        schema: dict[str, Any],
        correlation_id: str,
        metadata: dict[str, str],
        use_tools: bool,
        timeout: float,
        tool_catalogue: bool = False,
    ) -> Generation:
        body: dict[str, Any] = {
            "prompt": prompt,
            "system": system,
            "schema": schema,
            "correlation_id": correlation_id,
            "metadata": metadata,
        }
        if self._model:
            body["model"] = self._model
        if tool_catalogue:
            body["tool_catalogue"] = True
        path = "/generate" if use_tools else "/generate-plain"
        try:
            response = await self._client.post(
                path,
                json=body,
                timeout=httpx.Timeout(timeout, connect=3.0),
            )
        except httpx.TimeoutException as exc:
            raise _timeout() from exc
        except httpx.RequestError as exc:
            raise _unavailable() from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.is_error:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = "BAD_GATEWAY"
            message = f"AI-Mode returned HTTP {response.status_code}."
            if isinstance(error, dict):
                code = str(error.get("code") or code)
                message = str(error.get("message") or message)
            tools = payload.get("tools") if isinstance(payload, dict) else None
            raise AiModeError(code, message, tools if isinstance(tools, list) else [])

        try:
            data = payload["data"]
            tools = data.get("tools") or []
            generation = Generation(
                response=str(data["response"]),
                ai_run_id=str(data["run_id"]),
                model=str(data["model"]),
                tools=[tool for tool in tools if isinstance(tool, dict)],
            )
            finished = data.get("done") is not False and isinstance(tools, list)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise _malformed(what="generation") from exc
        if not finished:
            raise _malformed(what="generation")
        return generation
