"""The shared AI-Mode service, as this service sees it.

Nothing here knows what a model is. AI-Mode
(`ai-services/ai-mode`) owns the Ollama client, the approved-model allowlist and
the prompt/response bounds; this service asks it a question over HTTP the same
way it asks the shared reference service for a country id.

Failures map through the same `client.request` every other upstream uses, so an
AI-Mode outage is the documented 503 and a malformed answer is a 502.

The feature is optional. With `AI_MODE_URL` unset there is no client at all, and
every method says so rather than raising -- the accommodation service is a search
service that happens to have an ask box, not the other way round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException, status

from backend_service.client import request

if TYPE_CHECKING:
    from backend_service.config import Settings

UNAVAILABLE = "ai mode service unavailable"
NOT_CONFIGURED = "not_configured"
UNREACHABLE = "unreachable"
BAD_RESPONSE = "bad response from ai mode service"
# AI-Mode caps one MCP agent run at 180s; give it that plus the network.
AGENT_TIMEOUT = 200.0


class AssistError(HTTPException):
    """An AI-Mode failure that still carries the tool calls made before it, so
    the page can show what ran rather than only that something broke."""

    def __init__(self, status_code: int, detail: str, tools: list[Any]) -> None:
        super().__init__(status_code, detail)
        self.tools = tools


class AiClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        # `transport` is the same test seam the other three clients use.
        self._client = (
            httpx.AsyncClient(
                base_url=settings.ai_mode_url,
                timeout=settings.ai_mode_timeout,
                transport=transport,
            )
            if settings.ai_mode_url
            else None
        )

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def status(self) -> str:
        """What /health reports for this dependency.

        "not_configured" is a healthy answer: the operator turned the feature
        off, which is not the same as the service being broken.
        """
        if self._client is None:
            return NOT_CONFIGURED
        try:
            body = await request(
                self._client,
                "GET",
                "/health",
                unavailable=UNAVAILABLE,
                bad_response=BAD_RESPONSE,
            )
        except HTTPException:
            return UNREACHABLE
        return _unwrap(body).get("status", UNREACHABLE)

    async def generate(self, prompt: str, schema: dict[str, Any]) -> tuple[str, bool]:
        """Return final text and whether the run used tools (prevent action replay)."""
        if self._client is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "ai mode is not configured"
            )
        body = await request(
            self._client,
            "POST",
            "/generate",
            unavailable=UNAVAILABLE,
            bad_response=BAD_RESPONSE,
            json={"prompt": prompt, "schema": schema},
        )
        answer = _unwrap(body).get("response")
        if not isinstance(answer, str):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)
        return answer, bool(_unwrap(body).get("tools"))

    async def assist(
        self, prompt: str, system: str, correlation_id: str
    ) -> tuple[str, list[Any]]:
        """A free-text MCP agent run: the reply and AI-Mode's tool-call trace.

        Not `request()`: an AI-Mode error body carries the partial trace at the
        top level, and that helper discards error bodies.
        """
        if self._client is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "ai mode is not configured"
            )
        try:
            response = await self._client.post(
                "/generate",
                json={
                    "prompt": prompt,
                    "system": system,
                    "correlation_id": correlation_id,
                },
                timeout=AGENT_TIMEOUT,
            )
            body = response.json()
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, UNAVAILABLE
            ) from exc
        except ValueError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE) from exc
        if response.is_error:
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            tools = body.get("tools") if isinstance(body, dict) else None
            raise AssistError(
                # A timeout or outage keeps its status; anything else is 502.
                response.status_code
                if response.status_code in {503, 504}
                else status.HTTP_502_BAD_GATEWAY,
                str(message or BAD_RESPONSE),
                tools if isinstance(tools, list) else [],
            )
        data = _unwrap(body)
        answer, tools = data.get("response"), data.get("tools") or []
        if not isinstance(answer, str) or not isinstance(tools, list):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)
        return answer, tools


def _unwrap(body: Any) -> dict[str, Any]:
    """AI-Mode wraps every success in `{"data": ...}`. Its error envelope is a
    different shape, but `client.request` has already turned those into the
    right HTTPException by the time we get here."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)
    return body["data"]
