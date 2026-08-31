from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from ollama import AsyncClient, ResponseError
from pydantic import ValidationError

from .config import Settings
from .errors import (
    bad_gateway,
    dependency_response_too_large,
    dependency_timeout,
    dependency_unavailable,
    model_unavailable,
)
from .models import DependencyStatus


@dataclass(slots=True)
class ProviderGenerateResult:
    model: str
    response: str


class OllamaProviderAdapter:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = AsyncClient(
            host=settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.close()

    async def health(self) -> DependencyStatus:
        try:
            payload = await self._client.list()
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
        except (ConnectionError, httpx.NetworkError):
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
        except ResponseError as exc:
            return DependencyStatus(
                status="unavailable",
                service="ollama",
                detail=(
                    "Ollama reported an unexpected status while listing models: "
                    f"HTTP {exc.status_code}."
                ),
                code="DEPENDENCY_UNAVAILABLE",
            )
        except (ValidationError, ValueError):
            return DependencyStatus(
                status="invalid_response",
                service="ollama",
                detail="Ollama returned a malformed model list response.",
                code="BAD_GATEWAY",
            )

        available_models = {model.model for model in payload.models if model.model}
        if self._settings.default_model not in available_models:
            return DependencyStatus(
                status="degraded",
                service="ollama",
                detail=(
                    "Ollama responded, but the configured model "
                    f"'{self._settings.default_model}' is not available."
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
        model: str,
        prompt: str,
        schema: dict[str, Any] | None,
    ) -> ProviderGenerateResult:
        try:
            payload = await self._client.generate(
                model=model,
                prompt=prompt,
                format=schema,
                stream=False,
                raw=True,
                options={"temperature": 0},
            )
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "The AI provider did not respond before the configured timeout.",
                [{"field": "ai_mode", "issue": "provider request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            raise bad_gateway(
                "The AI provider returned an invalid HTTP response.",
                [{"field": "ai_mode", "issue": "provider returned invalid HTTP"}],
            ) from exc
        except (ConnectionError, httpx.NetworkError) as exc:
            raise dependency_unavailable(
                "The AI provider is unavailable.",
                [{"field": "ai_mode", "issue": "provider connection failed"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                "The AI provider request failed.",
                [{"field": "ai_mode", "issue": "provider request failed"}],
            ) from exc
        except ResponseError as exc:
            if _is_model_unavailable(exc):
                raise model_unavailable(
                    "Requested AI model is not available.",
                    [
                        {
                            "field": "model",
                            "issue": f"model '{model}' is not available in Ollama",
                        },
                    ],
                ) from exc
            raise dependency_unavailable(
                "The AI provider could not generate a response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": (
                            f"provider returned HTTP {exc.status_code}"
                            if exc.status_code > 0
                            else "provider rejected the generate request"
                        ),
                    },
                ],
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise bad_gateway(
                "The AI provider returned a malformed generate response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": "provider response body was malformed",
                    },
                ],
            ) from exc

        response_text = payload.response
        if payload.done is not True or response_text is None:
            raise bad_gateway(
                "The AI provider returned a malformed generate response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": (
                            "provider response did not contain a terminal "
                            "non-stream result"
                        ),
                    },
                ],
            )

        response_bytes = len(response_text.encode("utf-8"))
        if response_bytes > self._settings.max_response_bytes:
            raise dependency_response_too_large(
                (
                    "The AI provider returned a response that exceeded the "
                    "configured size limit."
                ),
                [
                    {
                        "field": "ai_mode",
                        "issue": (
                            "provider response exceeded "
                            f"{self._settings.max_response_bytes} bytes"
                        ),
                    },
                ],
            )

        return ProviderGenerateResult(
            model=payload.model or model,
            response=response_text,
        )


def _is_model_unavailable(exc: ResponseError) -> bool:
    error_text = _response_error_text(exc)
    lowered = error_text.casefold()
    return "model" in lowered and any(
        fragment in lowered for fragment in ("not found", "pull", "missing")
    )


def _response_error_text(exc: ResponseError) -> str:
    raw_error = exc.error if isinstance(exc.error, str) else str(exc.error)
    try:
        payload = json.loads(raw_error)
    except ValueError:
        return raw_error

    extracted = _extract_error_message(payload)
    if extracted is not None:
        return extracted
    return raw_error


def _extract_error_message(payload: object) -> str | None:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return None

    error_value = payload.get("error")
    if isinstance(error_value, str):
        return error_value
    if isinstance(error_value, dict):
        for key in ("message", "detail", "error"):
            candidate = error_value.get(key)
            if isinstance(candidate, str):
                return candidate

    for key in ("message", "detail"):
        candidate = payload.get(key)
        if isinstance(candidate, str):
            return candidate

    return None
