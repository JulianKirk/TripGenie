from __future__ import annotations

from typing import Any

import httpx
from pydantic import ConfigDict, Field, ValidationError, model_validator

from .config import Settings
from .errors import (
    bad_gateway,
    dependency_response_too_large,
    dependency_timeout,
    dependency_unavailable,
)
from .models import DependencyStatus, StrictModel


class OllamaResponseModel(StrictModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class OllamaModelSummary(OllamaResponseModel):
    model: str | None = None
    name: str | None = None

    @model_validator(mode="after")
    def ensure_identifier(self) -> "OllamaModelSummary":
        if self.identifier is None:
            raise ValueError("must include either 'name' or 'model'")
        return self

    @property
    def identifier(self) -> str | None:
        return self.name or self.model


class OllamaTagsResponse(OllamaResponseModel):
    models: list[OllamaModelSummary] = Field(default_factory=list)


class OllamaGenerateResponse(OllamaResponseModel):
    model: str | None = None
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
        self._cached_status: DependencyStatus | None = None
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
            status = DependencyStatus(
                status="not_configured",
                service="ollama",
                detail=(
                    "Ollama AI mode is disabled because no runtime base URL is "
                    "configured."
                ),
            )
            self._cache_status(status)
            return status

        try:
            response = await self._client.get("/api/tags")
        except httpx.TimeoutException:
            status = DependencyStatus(
                status="timeout",
                service="ollama",
                detail="Ollama did not respond before the configured timeout.",
                code="DEPENDENCY_TIMEOUT",
            )
            self._cache_status(status)
            return status
        except httpx.ProtocolError:
            status = DependencyStatus(
                status="invalid_response",
                service="ollama",
                detail="Ollama returned an invalid HTTP response.",
                code="BAD_GATEWAY",
            )
            self._cache_status(status)
            return status
        except httpx.NetworkError:
            status = DependencyStatus(
                status="unavailable",
                service="ollama",
                detail="Ollama is unavailable.",
                code="DEPENDENCY_UNAVAILABLE",
            )
            self._cache_status(status)
            return status
        except httpx.RequestError:
            status = DependencyStatus(
                status="unavailable",
                service="ollama",
                detail="Ollama request failed.",
                code="DEPENDENCY_UNAVAILABLE",
            )
            self._cache_status(status)
            return status

        if response.status_code != 200:
            status = DependencyStatus(
                status="degraded",
                service="ollama",
                detail=(
                    "Ollama reported an unexpected status while listing models: "
                    f"HTTP {response.status_code}."
                ),
                code="DEPENDENCY_UNAVAILABLE",
            )
            self._cache_status(status)
            return status

        try:
            payload = OllamaTagsResponse.model_validate(self._decode_json(response))
        except ValidationError:
            status = DependencyStatus(
                status="invalid_response",
                service="ollama",
                detail="Ollama returned a malformed model list response.",
                code="BAD_GATEWAY",
            )
            self._cache_status(status)
            return status

        available_models = {
            model.identifier for model in payload.models if model.identifier
        }
        if self._settings.ollama_model not in available_models:
            status = DependencyStatus(
                status="degraded",
                service="ollama",
                detail=(
                    "Ollama responded, but the configured model "
                    f"'{self._settings.ollama_model}' is not available."
                ),
                code="MODEL_UNAVAILABLE",
            )
            self._cache_status(status)
            return status

        status = DependencyStatus(
            status="ok",
            service="ollama",
            detail=(
                "Ollama responded successfully and the configured model is "
                "available."
            ),
        )
        self._cache_status(status)
        return status

    def readiness_status(self) -> DependencyStatus:
        if self._settings.ollama_base_url is None:
            return DependencyStatus(
                status="not_configured",
                service="ollama",
                detail=(
                    "Ollama AI mode is disabled because no runtime base URL is "
                    "configured. Backend readiness is based on the database only."
                ),
            )

        if self._cached_status is None:
            return DependencyStatus(
                status="not_checked",
                service="ollama",
                detail=(
                    "Ollama was not probed during /ready. Backend readiness is "
                    "based on the database only."
                ),
            )

        detail = self._cached_status.detail or "Last known Ollama status is cached."
        return DependencyStatus(
            status=self._cached_status.status,
            service=self._cached_status.service,
            detail=(
                f"{detail} This Ollama status is cached and non-authoritative for "
                "backend readiness."
            ),
            code=self._cached_status.code,
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
            self._cache_status(
                DependencyStatus(
                    status="invalid_response",
                    service="ollama",
                    detail="Ollama returned a malformed generate response.",
                    code="BAD_GATEWAY",
                ),
            )
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
            self._cache_status(
                DependencyStatus(
                    status="invalid_response",
                    service="ollama",
                    detail="Ollama returned an incomplete generate response.",
                    code="BAD_GATEWAY",
                ),
            )
            raise bad_gateway(
                "Ollama returned an incomplete generate response.",
                [{"field": "ollama", "issue": "generation did not finish"}],
            )

        self._cache_status(
            DependencyStatus(
                status="ok",
                service="ollama",
                detail=(
                    "Ollama responded successfully and returned a terminal "
                    "non-stream generate response."
                ),
            ),
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
            self._cache_status(
                DependencyStatus(
                    status="timeout",
                    service="ollama",
                    detail="Ollama did not respond before the configured timeout.",
                    code="DEPENDENCY_TIMEOUT",
                ),
            )
            raise dependency_timeout(
                "Ollama did not respond before the configured timeout.",
                [{"field": "ollama", "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            self._cache_status(
                DependencyStatus(
                    status="invalid_response",
                    service="ollama",
                    detail="Ollama returned an invalid HTTP response.",
                    code="BAD_GATEWAY",
                ),
            )
            raise bad_gateway(
                "Ollama returned an invalid HTTP response.",
                [{"field": "ollama", "issue": "dependency returned invalid HTTP"}],
            ) from exc
        except httpx.NetworkError as exc:
            self._cache_status(
                DependencyStatus(
                    status="unavailable",
                    service="ollama",
                    detail="Ollama is unavailable.",
                    code="DEPENDENCY_UNAVAILABLE",
                ),
            )
            raise dependency_unavailable(
                "Ollama is unavailable.",
                [{"field": "ollama", "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError:
            self._cache_status(
                DependencyStatus(
                    status="unavailable",
                    service="ollama",
                    detail="Ollama request failed.",
                    code="DEPENDENCY_UNAVAILABLE",
                ),
            )
            raise dependency_unavailable(
                "Ollama request failed.",
                [{"field": "ollama", "issue": "request could not be completed"}],
            ) from None

    def _ensure_size_limit(self, response: httpx.Response) -> None:
        if len(response.content) <= self._settings.ollama_max_response_bytes:
            return

        self._cache_status(
            DependencyStatus(
                status="invalid_response",
                service="ollama",
                detail=(
                    "Ollama returned a response that exceeded the configured "
                    "size limit."
                ),
                code="DEPENDENCY_RESPONSE_TOO_LARGE",
            ),
        )
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
        self._cache_status(
            DependencyStatus(
                status="unavailable",
                service="ollama",
                detail="Ollama could not generate itinerary suggestions.",
                code="DEPENDENCY_UNAVAILABLE",
            ),
        )
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

    def _cache_status(self, status: DependencyStatus) -> None:
        self._cached_status = status


def _ollama_error_message(response: httpx.Response) -> str | None:
    try:
        payload = OllamaErrorBody.model_validate(response.json())
    except (ValidationError, ValueError):
        return None
    return payload.error.strip() or None
