from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import TransportRecommendationDraft

_AI_FIELD = "ai_mode"

# Statuses AI-Mode produces deliberately and that mean "the dependency is
# temporarily unusable" rather than "this service sent a bad request".
_PASSTHROUGH_STATUSES = frozenset({503, 504})


class _GenerateData(BaseModel):
    """The part of AI-Mode's reply this service relies on.

    Extra fields are ignored on purpose: AI-Mode adding a field must not break
    transport recommendations.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str
    model: str
    provider: str = "ollama"
    response: str
    done: bool = True


class _GenerateEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: _GenerateData


class GeneratedDraft(BaseModel):
    """A validated draft plus the provenance needed to cite the run."""

    model_config = ConfigDict(extra="forbid")

    draft: TransportRecommendationDraft
    run_id: str
    model: str
    provider: str


class AiModeClient:
    """Client for the shared AI-Mode service.

    AI-Mode owns the boundary to Ollama and nothing else: this service renders
    its own prompt, validates the reply against its own schema, and keeps human
    approval and persistence on this side of the call.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=settings.ai_mode_base_url,
            timeout=settings.ai_mode_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def generate_draft(
        self,
        *,
        prompt: str,
        correlation_id: str,
        metadata: dict[str, str],
    ) -> GeneratedDraft:
        try:
            response = self._client.post(
                "/generate",
                json={
                    "prompt": prompt,
                    # AI-Mode passes the schema to the provider so the reply is
                    # JSON shaped like the draft this service expects.
                    "schema": TransportRecommendationDraft.model_json_schema(),
                    "correlation_id": correlation_id,
                    "metadata": metadata,
                },
            )
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "The AI recommendation timed out.",
                [{"field": _AI_FIELD, "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                "AI-Mode is unavailable.",
                [{"field": _AI_FIELD, "issue": "connection failed"}],
            ) from exc

        if response.is_error:
            self._raise_dependency_error(response)

        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> GeneratedDraft:
        try:
            generated = _GenerateEnvelope.model_validate(response.json()).data
        except (ValueError, ValidationError) as exc:
            raise bad_gateway(
                "AI-Mode returned a malformed generation response.",
                [{"field": _AI_FIELD, "issue": "envelope did not match"}],
            ) from exc

        if not generated.done:
            raise bad_gateway(
                "AI-Mode did not finish generating.",
                [{"field": _AI_FIELD, "issue": "generation was incomplete"}],
            )

        try:
            draft = TransportRecommendationDraft.model_validate_json(
                generated.response,
            )
        except (ValueError, ValidationError) as exc:
            # A model that ignores the schema is a dependency problem, not the
            # caller's fault, and must never reach a template half-formed.
            raise bad_gateway(
                "The AI reply did not match the recommendation schema.",
                [{"field": _AI_FIELD, "issue": "reply did not match the schema"}],
            ) from exc

        return GeneratedDraft(
            draft=draft,
            run_id=generated.run_id,
            model=generated.model,
            provider=generated.provider,
        )

    @staticmethod
    def _raise_dependency_error(response: httpx.Response) -> None:
        try:
            payload: dict[str, Any] = response.json()
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
        except ValueError:
            error = {}

        status_code = (
            response.status_code
            if response.status_code in _PASSTHROUGH_STATUSES
            else 502
        )
        details = error.get("details") or [
            {"field": _AI_FIELD, "issue": "request failed"},
        ]
        raise ApiError(
            status_code=status_code,
            code=str(error.get("code", "DEPENDENCY_UNAVAILABLE")),
            message=str(
                error.get("message", "AI recommendations are currently unavailable."),
            ),
            details=details,
        )
