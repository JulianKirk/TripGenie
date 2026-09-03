from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_error
from .models import BudgetAnalysis, BudgetAnalysisResponse


class _GenerateData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    model: str
    provider: str
    response: str
    done: bool


class _GenerateEnvelope(BaseModel):
    data: _GenerateData


class AiModeClient:
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
        )

    def close(self) -> None:
        self._client.close()

    def generate(
        self,
        *,
        prompt: str,
        correlation_id: str,
        metadata: dict[str, str],
    ) -> BudgetAnalysisResponse:
        try:
            response = self._client.post(
                "/generate",
                json={
                    "prompt": prompt,
                    "schema": BudgetAnalysis.model_json_schema(),
                    "correlation_id": correlation_id,
                    "metadata": metadata,
                },
            )
        except httpx.TimeoutException as exc:
            raise ApiError(
                504,
                "DEPENDENCY_TIMEOUT",
                "The AI analysis timed out.",
                [{"field": "ai_mode", "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_error("ai_mode", "connection failed") from exc

        if response.is_error:
            self._raise_dependency_error(response)

        try:
            generated = _GenerateEnvelope.model_validate(response.json()).data
            if not generated.done:
                raise ValueError("generation did not finish")
            analysis = BudgetAnalysis.model_validate_json(generated.response)
        except (ValueError, ValidationError) as exc:
            raise bad_gateway(
                "ai_mode", "response did not match the analysis schema"
            ) from exc

        return BudgetAnalysisResponse(
            analysis=analysis,
            run_id=generated.run_id,
            model=generated.model,
            provider=generated.provider,
        )

    @staticmethod
    def _raise_dependency_error(response: httpx.Response) -> None:
        try:
            error: dict[str, Any] = response.json().get("error", {})
        except ValueError:
            error = {}
        status_code = (
            response.status_code if response.status_code in {503, 504} else 502
        )
        raise ApiError(
            status_code,
            str(error.get("code", "DEPENDENCY_UNAVAILABLE")),
            str(error.get("message", "AI analysis is currently unavailable.")),
            error.get("details", [{"field": "ai_mode", "issue": "request failed"}]),
        )