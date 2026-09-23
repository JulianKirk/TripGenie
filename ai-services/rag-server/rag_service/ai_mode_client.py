from __future__ import annotations

import math
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError

from .errors import (
    ApiError,
    bad_gateway,
    dependency_timeout,
    dependency_unavailable,
)
from .models import (
    AiEmbedPayload,
    AiGeneratePayload,
    AiModeHealthPayload,
    DataEnvelope,
    DependencyStatus,
    ErrorEnvelope,
)

if TYPE_CHECKING:
    from .config import Settings

MALFORMED_EMBED_MESSAGE = "AI-Mode returned a malformed embedding response."
MALFORMED_GENERATE_MESSAGE = "AI-Mode returned a malformed generation response."
AI_MODE_TIMEOUT_MESSAGE = "AI-Mode did not respond before the configured timeout."
AI_MODE_UNAVAILABLE_MESSAGE = "AI-Mode is unavailable."
INVALID_ERROR_MESSAGE = "AI-Mode returned an invalid error response."
INCOMPATIBLE_EMBED_MESSAGE = "AI-Mode returned a malformed embedding response."


class AiModeClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ai_mode_base_url,
            timeout=settings.ai_mode_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> DependencyStatus:
        try:
            response = await self._client.get("/ready")
        except httpx.TimeoutException:
            return DependencyStatus(
                status="timeout",
                service="ai-mode",
                detail="AI-Mode did not respond before the configured timeout.",
                code="DEPENDENCY_TIMEOUT",
            )
        except httpx.RequestError:
            return DependencyStatus(
                status="unavailable",
                service="ai-mode",
                detail="AI-Mode is unavailable.",
                code="DEPENDENCY_UNAVAILABLE",
            )
        if response.status_code != 200:
            return DependencyStatus(
                status="unavailable",
                service="ai-mode",
                detail=f"AI-Mode readiness returned HTTP {response.status_code}.",
                code="DEPENDENCY_UNAVAILABLE",
            )
        try:
            payload = (
                DataEnvelope[AiModeHealthPayload].model_validate(response.json()).data
            )
        except (ValidationError, ValueError):
            return DependencyStatus(
                status="invalid_response",
                service="ai-mode",
                detail="AI-Mode returned a malformed readiness response.",
                code="BAD_GATEWAY",
            )
        if payload.status not in {"ok", "ready"}:
            return DependencyStatus(
                status="unavailable",
                service="ai-mode",
                detail="AI-Mode reported that it is not ready.",
                code="DEPENDENCY_UNAVAILABLE",
            )
        return DependencyStatus(
            status="ok",
            service="ai-mode",
            detail="AI-Mode is ready.",
        )

    async def embed(
        self,
        inputs: list[str],
        *,
        correlation_id: str,
    ) -> AiEmbedPayload:
        response = await self._request(
            "/embed",
            {
                "inputs": inputs,
                "model": self._settings.embedding_model,
                "correlation_id": correlation_id,
                "metadata": {"feature": "shared-rag"},
            },
        )
        try:
            payload = DataEnvelope[AiEmbedPayload].model_validate(response.json()).data
        except (ValidationError, ValueError) as exc:
            raise bad_gateway(
                MALFORMED_EMBED_MESSAGE,
                field="ai_mode",
                issue="embedding response did not match the contract",
            ) from exc
        invalid = (
            payload.model != self._settings.embedding_model
            or payload.correlation_id != correlation_id
            or len(payload.embeddings) != len(inputs)
            or any(
                len(vector) != payload.dimension
                or not all(math.isfinite(value) for value in vector)
                for vector in payload.embeddings
            )
        )
        if invalid:
            raise bad_gateway(
                INCOMPATIBLE_EMBED_MESSAGE,
                field="ai_mode",
                issue="embedding response was incompatible with the request",
            )
        return payload

    async def generate(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        correlation_id: str,
    ) -> AiGeneratePayload:
        response = await self._request(
            "/generate",
            {
                "prompt": prompt,
                "schema": schema,
                "correlation_id": correlation_id,
                "metadata": {"feature": "shared-rag"},
            },
        )
        try:
            payload = (
                DataEnvelope[AiGeneratePayload].model_validate(response.json()).data
            )
        except (ValidationError, ValueError) as exc:
            raise bad_gateway(
                MALFORMED_GENERATE_MESSAGE,
                field="ai_mode",
                issue="generation response did not match the contract",
            ) from exc
        if not payload.done or payload.correlation_id != correlation_id:
            raise bad_gateway(
                MALFORMED_GENERATE_MESSAGE,
                field="ai_mode",
                issue="generation response was incomplete or mismatched",
            )
        return payload

    async def _request(self, path: str, payload: dict[str, object]) -> httpx.Response:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                AI_MODE_TIMEOUT_MESSAGE,
                field="ai_mode",
                issue="request timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                AI_MODE_UNAVAILABLE_MESSAGE,
                field="ai_mode",
                issue="connection failed",
            ) from exc
        if response.status_code < 400:
            return response

        try:
            error = ErrorEnvelope.model_validate(response.json()).error
        except (ValidationError, ValueError) as exc:
            raise bad_gateway(
                INVALID_ERROR_MESSAGE,
                field="ai_mode",
                issue=f"unexpected HTTP {response.status_code}",
            ) from exc
        raise ApiError(
            status_code=response.status_code,
            code=error.code,
            message=error.message,
            retryable=response.status_code in {503, 504},
            details=[detail.model_dump() for detail in error.details],
        )
