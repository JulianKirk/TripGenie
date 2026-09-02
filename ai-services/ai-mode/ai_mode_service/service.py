from __future__ import annotations

import json
import logging
from uuid import uuid4

from pydantic import ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, validation_error
from .models import (
    GenerateRequest,
    GenerateResponsePayload,
    HealthDependencies,
    HealthResponse,
)
from .provider import OllamaProviderAdapter

LOGGER = logging.getLogger(__name__)
VALIDATION_ERROR_MESSAGE = "One or more fields failed validation."
LOG_VALUE_MAX_CHARS = 160


class AiModeService:
    def __init__(self, provider: OllamaProviderAdapter, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def health(self) -> HealthResponse:
        ollama = await self._provider.health()
        overall_status = "ok" if ollama.status == "ok" else "degraded"
        return HealthResponse(
            status=overall_status,
            service=self._settings.service_name,
            dependencies=HealthDependencies(ollama=ollama),
        )

    async def ready(self) -> tuple[int, HealthResponse]:
        ollama = await self._provider.health()
        is_ready = ollama.status == "ok"
        return (
            200 if is_ready else 503,
            HealthResponse(
                status="ok" if is_ready else "unavailable",
                service=self._settings.service_name,
                dependencies=HealthDependencies(ollama=ollama),
            ),
        )

    async def generate(self, payload: GenerateRequest) -> GenerateResponsePayload:
        self._validate_payload_bounds(payload)
        resolved_model = self._resolve_model(payload.model)
        run_id = f"aimode_{uuid4().hex[:12]}"
        correlation_id = _normalise_correlation_id(payload.correlation_id, run_id)
        schema_chars = _json_char_count(payload.output_schema)

        _log_stage(
            "start",
            run_id=run_id,
            correlation_id=correlation_id,
            model=resolved_model,
            prompt_chars=len(payload.prompt),
            schema_chars=schema_chars,
            metadata_count=len(payload.metadata),
        )

        try:
            result = await self._provider.generate(
                model=resolved_model,
                prompt=payload.prompt,
                schema=payload.output_schema,
            )
        except ApiError as exc:
            _log_stage(
                "failure",
                run_id=run_id,
                correlation_id=correlation_id,
                model=resolved_model,
                error_code=exc.code,
                status_code=exc.status_code,
            )
            raise

        try:
            response_payload = GenerateResponsePayload(
                run_id=run_id,
                correlation_id=correlation_id,
                model=result.model,
                provider="ollama",
                response=result.response,
                done=True,
            )
        except ValidationError as exc:
            raise bad_gateway(
                "The AI provider returned a malformed generate response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": "provider response body was malformed",
                    },
                ],
            ) from exc

        _log_stage(
            "success",
            run_id=run_id,
            correlation_id=correlation_id,
            model=response_payload.model,
            response_bytes=len(response_payload.response.encode("utf-8")),
        )
        return response_payload

    def _resolve_model(self, model_override: str | None) -> str:
        model = model_override or self._settings.default_model
        if model not in self._settings.allowed_models:
            approved_models = ", ".join(self._settings.allowed_models)
            raise validation_error(
                VALIDATION_ERROR_MESSAGE,
                [
                    {
                        "field": "model",
                        "issue": f"must be one of: {approved_models}",
                    },
                ],
            )
        return model

    def _validate_payload_bounds(self, payload: GenerateRequest) -> None:
        details: list[dict[str, str]] = []
        if len(payload.prompt) > self._settings.max_prompt_chars:
            details.append(
                {
                    "field": "prompt",
                    "issue": (
                        "must be at most "
                        f"{self._settings.max_prompt_chars} characters"
                    ),
                },
            )

        if payload.output_schema is not None:
            schema_chars = _json_char_count(payload.output_schema)
            if schema_chars > self._settings.max_schema_chars:
                details.append(
                    {
                        "field": "schema",
                        "issue": (
                            "must serialise to at most "
                            f"{self._settings.max_schema_chars} characters"
                        ),
                    },
                )

        if details:
            raise validation_error(VALIDATION_ERROR_MESSAGE, details)


def _json_char_count(payload: object | None) -> int:
    if payload is None:
        return 0
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _normalise_correlation_id(correlation_id: str | None, fallback: str) -> str:
    cleaned = (correlation_id or "").strip()
    return cleaned or fallback


def _log_stage(stage: str, **payload: object) -> None:
    serialised = " ".join(
        f"{key}={_sanitise_log_value(payload[key])}" for key in sorted(payload)
    )
    LOGGER.info("ai_mode stage=%s %s", stage, serialised)


def _sanitise_log_value(value: object) -> str:
    text = "None" if value is None else str(value)
    cleaned = "".join(
        character
        if (
            character not in {"\u2028", "\u2029"}
            and ord(character) >= 32
            and ord(character) != 127
        )
        else "?"
        for character in text
    )
    if len(cleaned) <= LOG_VALUE_MAX_CHARS:
        return cleaned
    return f"{cleaned[: LOG_VALUE_MAX_CHARS - 1]}…"
