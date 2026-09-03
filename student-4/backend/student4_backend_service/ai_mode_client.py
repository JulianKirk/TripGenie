from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from .config import Settings


class _GenerateData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    model: str
    provider: str = "ollama"
    response: str
    done: bool = True


class _GenerateEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: _GenerateData


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str
    run_id: str
    model: str
    provider: str


class AiModeClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = (
            httpx.AsyncClient(
                base_url=settings.ai_mode_url,
                timeout=settings.ai_mode_timeout,
                transport=transport,
                follow_redirects=False,
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

    async def generate(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        correlation_id: str,
        metadata: dict[str, str],
    ) -> GeneratedAnswer:
        if self._client is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "AI recommendations are not configured.",
            )
        try:
            response = await self._client.post(
                "/generate",
                json={
                    "prompt": prompt,
                    "schema": schema,
                    "correlation_id": correlation_id,
                    "metadata": metadata,
                },
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status.HTTP_504_GATEWAY_TIMEOUT,
                "AI recommendations timed out.",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "AI recommendations are unavailable.",
            ) from exc

        if response.is_error:
            upstream_status = response.status_code
            public_status = upstream_status if upstream_status in {503, 504} else 502
            raise HTTPException(public_status, "AI recommendations are unavailable.")

        try:
            generated = _GenerateEnvelope.model_validate(response.json()).data
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "AI Mode returned a malformed response.",
            ) from exc
        if not generated.done:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "AI Mode did not finish generating.",
            )
        return GeneratedAnswer(
            response=generated.response,
            run_id=generated.run_id,
            model=generated.model,
            provider=generated.provider,
        )
