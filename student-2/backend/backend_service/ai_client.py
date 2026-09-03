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

    async def generate(self, prompt: str, schema: dict[str, Any]) -> str:
        """The model's raw answer, constrained to `schema`.

        AI-Mode forwards the schema to Ollama as its `format`, so what comes
        back is JSON of that shape -- but it is still just a string here.
        Nothing validates it against the schema on either side of the wire;
        that is `ai_search`'s job, and the reason it can retry.
        """
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
        return answer


def _unwrap(body: Any) -> dict[str, Any]:
    """AI-Mode wraps every success in `{"data": ...}`. Its error envelope is a
    different shape, but `client.request` has already turned those into the
    right HTTPException by the time we get here."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)
    return body["data"]
