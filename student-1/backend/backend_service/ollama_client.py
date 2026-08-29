from __future__ import annotations

from typing import Any

import httpx
from pydantic import Field, ValidationError

from .config import Settings
from .errors import (
    bad_gateway,
    dependency_response_too_large,
    dependency_timeout,
    dependency_unavailable,
)
from .models import DependencyStatus, StrictModel


class OllamaModelSummary(StrictModel):
    model: str | None = None
    name: str | None = None


class OllamaTagsResponse(StrictModel):
    models: list[OllamaModelSummary] = Field(default_factory=list)


class OllamaGenerateResponse(StrictModel):
    model: str
    response: str
    done: bool
    done_reason: str | None = None
    created_at: str | None = None


class OllamaErrorBody(StrictModel):
    error: str


class OllamaClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = (
            httpx.AsyncClient(
                base_url=settings.ollama_base_url,
                timeout=settings.ollama_timeout_seconds,
                transport=transport,
                follow_redirects=False,
            )
            if settings.ollama_base_url is not None
            else None
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def health(self) -> DependencyStatus:
        if self._client is None:
            return DependencyStatus(
                status="not_configured",
                service="ollama",
                detail=(
                    "Ollama AI mode is disabled because no runtime base URL is "
                    "configured."
                ),
            )

        try:
            response = await self._client.get("/api/tags")
        except httpx.TimeoutException:
            return DependencyStatus(
                status="timeout",
                service="ollama",
                detail="Ollama did not respond before the configured timeout.",
                code="DEPENDENCY_TIMEOUT",
            )
        except httpx.ProtocolError:
            return DependencyStatus(
                status="invalid_response",
                service="ollama",
                detail="Ollama returned an invalid HTTP response.",
                code="BAD_GATEWAY",
            )
        except httpx.NetworkError:
            return DependencyStatus(
                status="unavailable",
                service="ollama",
                detail="Ollama is unavailable.",
                code="DEPENDENCY_UNAVAILABLE",
            )
        except httpx.RequestError:
            return DependencyStatus(
                status="unavailable",
                service="ollama",
                detail="Ollama request failed.",
                code="DEPENDENCY_UNAVAILABLE",
            )

        if response.status_code != 200:
            return DependencyStatus(
                status="degraded",
                service="ollama",
                detail=(
                    "Ollama reported an unexpected status while listing models: "
                    f"HTTP {response.status_code}."
                ),
                code="DEPENDENCY_UNAVAILABLE",
            )

        try:
            payload = OllamaTagsResponse.model_validate(self._decode_json(response))
        except ValidationError:
            return DependencyStatus(
                status="invalid_response",
                service="ollama",
                detail="Ollama returned a malformed model list response.",
                code="BAD_GATEWAY",
            )

        available_models = {
            model_name
            for model in payload.models
            for model_name in (model.model, model.name)
            if model_name
        }
        if self._settings.ollama_model not in available_models:
            return DependencyStatus(
                status="degraded",
                service="ollama",
                detail=(
                    "Ollama responded, but the configured model "
                    f"'{self._settings.ollama_model}' is not available."
                ),
                code="MODEL_UNAVAILABLE",
            )

        return DependencyStatus(
            status="ok",
            service="ollama",
            detail=(
                "Ollama responded successfully and the configured model is "
                "available."
            ),
        )

    async def generate(
        self,
        *,
        prompt: str,
        schema: dict[str, object],
        run_id: str,
        correlation_id: str,
        attempt: int,
    ) -> OllamaGenerateResponse:
        client = self._require_client()
        response = await self._send(
            client,
            "POST",
            "/api/generate",
            json={
                "model": self._settings.ollama_model,
                "prompt": prompt,
                "format": schema,
                "stream": False,
                "options": {"temperature": 0},
            },
            run_id=run_id,
            correlation_id=correlation_id,
            attempt=attempt,
        )
        self._ensure_size_limit(response)
        if response.status_code != 200:
            self._raise_generation_error(response)

        payload = self._decode_json(
            response,
            message="Ollama returned a malformed generate response.",
        )
        try:
            generated = OllamaGenerateResponse.model_validate(payload)
        except ValidationError as exc:
            raise bad_gateway(
                "Ollama returned a malformed generate response.",
                [
                    {
                        "field": "ollama",
                        "issue": "response body did not match the expected schema",
                    },
                ],
            ) from exc

        if not generated.done:
            raise bad_gateway(
                "Ollama returned an incomplete generate response.",
                [{"field": "ollama", "issue": "generation did not finish"}],
            )

        return generated

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise dependency_unavailable(
                "AI suggestions are unavailable because Ollama is not configured.",
                [{"field": "ollama", "issue": "runtime base URL is not configured"}],
            )
        return self._client

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        run_id: str,
        correlation_id: str,
        attempt: int,
    ) -> httpx.Response:
        try:
            return await client.request(
                method,
                path,
                json=json,
                headers={
                    "X-Request-ID": run_id,
                    "X-Correlation-ID": correlation_id,
                    "X-AI-Attempt": str(attempt),
                },
            )
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "Ollama did not respond before the configured timeout.",
                [{"field": "ollama", "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            raise bad_gateway(
                "Ollama returned an invalid HTTP response.",
                [{"field": "ollama", "issue": "dependency returned invalid HTTP"}],
            ) from exc
        except httpx.NetworkError as exc:
            raise dependency_unavailable(
                "Ollama is unavailable.",
                [{"field": "ollama", "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError:
            raise dependency_unavailable(
                "Ollama request failed.",
                [{"field": "ollama", "issue": "request could not be completed"}],
            ) from None

    def _ensure_size_limit(self, response: httpx.Response) -> None:
        if len(response.content) <= self._settings.ollama_max_response_bytes:
            return

        raise dependency_response_too_large(
            "Ollama returned a response that exceeded the configured size limit.",
            [
                {
                    "field": "ollama",
                    "issue": (
                        f"response size exceeded "
                        f"{self._settings.ollama_max_response_bytes} bytes"
                    ),
                },
            ],
        )

    def _raise_generation_error(self, response: httpx.Response) -> None:
        error_message = _ollama_error_message(response)
        raise dependency_unavailable(
            "Ollama could not generate itinerary suggestions.",
            [
                {
                    "field": "ollama",
                    "issue": error_message
                    or f"dependency returned HTTP {response.status_code}",
                },
            ],
        )

    @staticmethod
    def _decode_json(
        response: httpx.Response,
        *,
        message: str = "Ollama returned malformed JSON.",
    ) -> object:
        try:
            return response.json()
        except ValueError as exc:
            raise bad_gateway(
                message,
                [{"field": "ollama", "issue": "response body was not valid JSON"}],
            ) from exc


def _ollama_error_message(response: httpx.Response) -> str | None:
    try:
        payload = OllamaErrorBody.model_validate(response.json())
    except (ValidationError, ValueError):
        return None
    return payload.error.strip() or None
