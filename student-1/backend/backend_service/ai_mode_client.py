from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import ConfigDict, TypeAdapter, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import (
    DataEnvelope,
    DependencyStatus,
    ErrorEnvelope,
    ShortText,
    StrictModel,
)

T = TypeVar("T")

HANDLED_ERROR_STATUSES = {422, 502, 503, 504}


class AiModeResponseModel(StrictModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class AiModeHealthDependencies(AiModeResponseModel):
    ollama: DependencyStatus


class AiModeHealthPayload(AiModeResponseModel):
    status: ShortText
    service: ShortText
    dependencies: AiModeHealthDependencies


class AiModeGeneratePayload(AiModeResponseModel):
    run_id: ShortText
    correlation_id: ShortText
    model: ShortText
    provider: ShortText | None = None
    response: str
    done: bool


class AiModeClient:
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
                base_url=settings.ai_mode_base_url,
                timeout=settings.ai_mode_timeout_seconds,
                transport=transport,
                follow_redirects=False,
            )
            if settings.ai_mode_base_url is not None
            else None
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def health(self) -> DependencyStatus:
        if self._client is None:
            status = DependencyStatus(
                status="not_configured",
                service="ai-mode",
                detail=(
                    "Shared AI-Mode is disabled because no runtime base URL is "
                    "configured."
                ),
            )
            self._cache_status(status)
            return status

        try:
            envelope = await self._request_model(
                "GET",
                "/health",
                expected_statuses={200},
                response_type=DataEnvelope[AiModeHealthPayload],
                malformed_message=(
                    "AI-Mode service returned a malformed health response."
                ),
            )
        except ApiError as exc:
            status = self._dependency_status_from_error(exc)
            self._cache_status(status)
            return status

        ollama_status = envelope.data.dependencies.ollama
        if envelope.data.status == "ok" and ollama_status.status == "ok":
            status = DependencyStatus(
                status="ok",
                service=envelope.data.service,
                detail="AI-Mode service responded successfully.",
            )
            self._cache_status(status)
            return status

        status = DependencyStatus(
            status="degraded",
            service=envelope.data.service,
            detail=(
                ollama_status.detail
                or f"AI-Mode service reported status '{envelope.data.status}'."
            ),
            code=ollama_status.code,
        )
        self._cache_status(status)
        return status

    def readiness_status(self) -> DependencyStatus:
        if self._settings.ai_mode_base_url is None:
            return DependencyStatus(
                status="not_configured",
                service="ai-mode",
                detail=(
                    "Shared AI-Mode is disabled because no runtime base URL is "
                    "configured. Backend readiness is based on the database only."
                ),
            )

        if self._cached_status is None:
            return DependencyStatus(
                status="not_checked",
                service="ai-mode",
                detail=(
                    "Shared AI-Mode was not probed during /ready. Backend "
                    "readiness is based on the database only."
                ),
            )

        detail = self._cached_status.detail or "Last known AI-Mode status is cached."
        return DependencyStatus(
            status=self._cached_status.status,
            service=self._cached_status.service,
            detail=(
                f"{detail} This AI-Mode status is cached and non-authoritative "
                "for backend readiness."
            ),
            code=self._cached_status.code,
        )

    async def generate(
        self,
        *,
        prompt: str,
        schema: dict[str, object],
        correlation_id: str,
        metadata: dict[str, str],
    ) -> AiModeGeneratePayload:
        self._require_client()
        envelope = await self._request_model(
            "POST",
            "/generate",
            json={
                "prompt": prompt,
                "schema": schema,
                "correlation_id": correlation_id,
                "metadata": metadata,
            },
            expected_statuses={200},
            response_type=DataEnvelope[AiModeGeneratePayload],
            malformed_message="AI-Mode service returned a malformed generate response.",
        )
        if envelope.data.done is not True:
            status = DependencyStatus(
                status="invalid_response",
                service="ai-mode",
                detail="AI-Mode service returned a malformed generate response.",
                code="BAD_GATEWAY",
            )
            self._cache_status(status)
            raise bad_gateway(
                "AI-Mode service returned a malformed generate response.",
                [{"field": "ai_mode", "issue": "generation did not finish"}],
            )

        self._cache_status(
            DependencyStatus(
                status="ok",
                service="ai-mode",
                detail="AI-Mode service responded successfully.",
            )
        )
        return envelope.data

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise dependency_unavailable(
                (
                    "AI suggestions are unavailable because the shared AI-Mode "
                    "service is not configured."
                ),
                [{"field": "ai_mode", "issue": "runtime base URL is not configured"}],
            )
        return self._client

    async def _request_model(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        expected_statuses: set[int],
        response_type: Any,
        malformed_message: str,
    ) -> T:
        response = await self._send(method, path, json=json)
        if response.status_code not in expected_statuses:
            self._raise_error_response(response)

        payload = self._decode_json(response, malformed_message)
        try:
            return TypeAdapter(response_type).validate_python(payload)
        except ValidationError as exc:
            raise bad_gateway(
                malformed_message,
                [
                    {
                        "field": "ai_mode",
                        "issue": "response body did not match the expected schema",
                    },
                ],
            ) from exc

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = self._require_client()
        try:
            return await client.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            status = DependencyStatus(
                status="timeout",
                service="ai-mode",
                detail=(
                    "Shared AI-Mode service did not respond before the "
                    "configured timeout."
                ),
                code="DEPENDENCY_TIMEOUT",
            )
            self._cache_status(status)
            raise dependency_timeout(
                "Shared AI-Mode service did not respond before the configured timeout.",
                [{"field": "ai_mode", "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            status = DependencyStatus(
                status="invalid_response",
                service="ai-mode",
                detail="AI-Mode service returned an invalid HTTP response.",
                code="BAD_GATEWAY",
            )
            self._cache_status(status)
            raise bad_gateway(
                "AI-Mode service returned an invalid HTTP response.",
                [{"field": "ai_mode", "issue": "dependency returned invalid HTTP"}],
            ) from exc
        except httpx.NetworkError as exc:
            status = DependencyStatus(
                status="unavailable",
                service="ai-mode",
                detail="Shared AI-Mode service is unavailable.",
                code="DEPENDENCY_UNAVAILABLE",
            )
            self._cache_status(status)
            raise dependency_unavailable(
                "Shared AI-Mode service is unavailable.",
                [{"field": "ai_mode", "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError:
            status = DependencyStatus(
                status="unavailable",
                service="ai-mode",
                detail="Shared AI-Mode service request failed.",
                code="DEPENDENCY_UNAVAILABLE",
            )
            self._cache_status(status)
            raise dependency_unavailable(
                "Shared AI-Mode service request failed.",
                [{"field": "ai_mode", "issue": "request could not be completed"}],
            ) from None

    @staticmethod
    def _decode_json(response: httpx.Response, message: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise bad_gateway(
                message,
                [{"field": "ai_mode", "issue": "response body was not valid JSON"}],
            ) from exc

    def _raise_error_response(self, response: httpx.Response) -> None:
        if response.status_code in HANDLED_ERROR_STATUSES:
            payload = self._decode_json(
                response,
                "AI-Mode service returned a malformed error response.",
            )
            try:
                envelope = ErrorEnvelope.model_validate(payload)
            except ValidationError as exc:
                raise bad_gateway(
                    "AI-Mode service returned a malformed error response.",
                    [
                        {
                            "field": "ai_mode",
                            "issue": "error body did not match the expected schema",
                        },
                    ],
                ) from exc

            api_error = ApiError(
                status_code=response.status_code,
                code=envelope.error.code,
                message=envelope.error.message,
                details=[
                    detail.model_dump(mode="json")
                    for detail in envelope.error.details
                ],
            )
            if response.status_code != 422:
                self._cache_status(self._dependency_status_from_error(api_error))
            raise api_error

        if response.status_code >= 500:
            status = DependencyStatus(
                status="unavailable",
                service="ai-mode",
                detail="AI-Mode service failed while processing the request.",
                code="BAD_GATEWAY",
            )
            self._cache_status(status)
            raise bad_gateway(
                "AI-Mode service failed while processing the request.",
                [
                    {
                        "field": "ai_mode",
                        "issue": f"dependency returned HTTP {response.status_code}",
                    },
                ],
            )

        raise bad_gateway(
            "AI-Mode service returned an unexpected response.",
            [
                {
                    "field": "ai_mode",
                    "issue": f"unexpected HTTP {response.status_code}",
                },
            ],
        )

    @staticmethod
    def _dependency_status_from_error(exc: ApiError) -> DependencyStatus:
        status_map = {
            "DEPENDENCY_TIMEOUT": "timeout",
            "DEPENDENCY_UNAVAILABLE": "unavailable",
            "BAD_GATEWAY": "invalid_response",
            "MODEL_UNAVAILABLE": "degraded",
            "DEPENDENCY_RESPONSE_TOO_LARGE": "invalid_response",
        }
        return DependencyStatus(
            status=status_map.get(exc.code, "unavailable"),
            service="ai-mode",
            detail=exc.message,
            code=exc.code,
        )

    def _cache_status(self, status: DependencyStatus) -> None:
        self._cached_status = status
