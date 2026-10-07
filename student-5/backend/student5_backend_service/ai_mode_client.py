from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_error
from .models import BudgetAnalysis, BudgetAnalysisResponse, ToolTrace


class _GenerateData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    model: str
    provider: str
    response: str
    done: bool
    tools: list[ToolTrace] = Field(default_factory=list)


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

    def _generate(
        self, body: dict[str, Any], *, timeout_message: str, schema_message: str
    ) -> _GenerateData:
        try:
            response = self._client.post("/generate", json=body)
        except httpx.TimeoutException as exc:
            raise ApiError(
                504,
                "DEPENDENCY_TIMEOUT",
                timeout_message,
                [{"field": "ai_mode", "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_error("ai_mode", "connection failed") from exc

        if response.is_error:
            self._raise_dependency_error(response)

        try:
            return _GenerateEnvelope.model_validate(response.json()).data
        except (ValueError, ValidationError) as exc:
            raise bad_gateway("ai_mode", schema_message) from exc

    def run_tools(
        self,
        *,
        prompt: str,
        system: str,
        correlation_id: str,
        metadata: dict[str, str],
    ) -> _GenerateData:
        generated = self._generate(
            {
                "prompt": prompt,
                "system": system,
                "correlation_id": correlation_id,
                "metadata": metadata,
            },
            timeout_message="The AI tool run timed out.",
            schema_message="response did not match the generate schema",
        )
        if not generated.done:
            raise bad_gateway("ai_mode", "generation did not finish")
        return generated

    def generate(
        self,
        *,
        prompt: str,
        correlation_id: str,
        metadata: dict[str, str],
    ) -> tuple[BudgetAnalysisResponse, bool]:
        generated = self._generate(
            {
                "prompt": prompt,
                "schema": BudgetAnalysis.model_json_schema(),
                "correlation_id": correlation_id,
                "metadata": metadata,
            },
            timeout_message="The AI analysis timed out.",
            schema_message="response did not match the analysis schema",
        )

        used_tools = bool(generated.tools)
        try:
            if not generated.done:
                raise ValueError("generation did not finish")
            analysis = BudgetAnalysis.model_validate_json(generated.response)
        except (ValueError, ValidationError) as exc:
            error = bad_gateway("ai_mode", "response did not match the analysis schema")
            error.retryable = not used_tools
            raise error from exc

        return (
            BudgetAnalysisResponse(
                analysis=analysis,
                run_id=generated.run_id,
                model=generated.model,
                provider=generated.provider,
            ),
            used_tools,
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
