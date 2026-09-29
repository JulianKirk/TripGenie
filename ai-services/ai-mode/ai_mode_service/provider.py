from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import (
    bad_gateway,
    dependency_response_too_large,
    dependency_timeout,
    dependency_unavailable,
    model_unavailable,
)
from .models import DependencyStatus, ProviderMessage


@dataclass(slots=True)
class ProviderEmbedResult:
    model: str
    embeddings: list[list[float]]


class OllamaProviderAdapter:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        headers = (
            {"Authorization": f"Bearer {settings.ollama_api_key}"}
            if settings.ollama_api_key
            else {}
        )
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
            transport=transport,
            headers=headers,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> DependencyStatus:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            payload = TypeAdapter(dict[str, Any]).validate_python(response.json())
            models = payload.get("models")
            if not isinstance(models, list) or any(
                not isinstance(item, dict) for item in models
            ):
                raise ValueError("Invalid model list")
            available_models = TypeAdapter(set[str]).validate_python(
                [item.get("model", item.get("name")) for item in models]
            )
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
        except httpx.HTTPStatusError as exc:
            return DependencyStatus(
                status="unavailable",
                service="ollama",
                detail=(
                    "Ollama reported an unexpected status while listing models: "
                    f"HTTP {exc.response.status_code}."
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

        required_models = tuple(
            dict.fromkeys(
                (
                    self._settings.default_model,
                    self._settings.default_embedding_model,
                )
            )
        )
        missing_models = [
            model
            for model in required_models
            if not _model_is_available(model, available_models)
        ]
        if missing_models:
            return DependencyStatus(
                status="degraded",
                service="ollama",
                detail=(
                    "Ollama responded, but configured models are unavailable: "
                    f"{', '.join(missing_models)}."
                ),
                code="MODEL_UNAVAILABLE",
            )

        return DependencyStatus(
            status="ok",
            service="ollama",
            detail=(
                "Ollama responded successfully and the configured models are available."
            ),
        )

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        schema: dict[str, Any] | None = None,
    ) -> ProviderMessage:
        try:
            # Preserve the complete MCP JSON Schema, including nested references.
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "format": schema,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_ctx": self._settings.context_tokens,
                    },
                },
            )
            response.raise_for_status()
            payload = TypeAdapter(dict[str, Any]).validate_python(response.json())
            message = ProviderMessage.model_validate(payload.get("message"))
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
        except httpx.HTTPStatusError as exc:
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
                            f"provider returned HTTP {exc.response.status_code}"
                            if exc.response.status_code > 0
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

        if payload.get("done") is not True:
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

        response_bytes = len(message.model_dump_json(exclude_none=True).encode("utf-8"))
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

        return message

    async def embed(
        self,
        *,
        model: str,
        inputs: list[str],
    ) -> ProviderEmbedResult:
        try:
            response = await self._client.post(
                "/api/embed", json={"model": model, "input": inputs}
            )
            response.raise_for_status()
            payload = TypeAdapter(dict[str, Any]).validate_python(response.json())
            embeddings = TypeAdapter(list[list[float]]).validate_python(
                payload.get("embeddings", [])
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
        except httpx.HTTPStatusError as exc:
            if _is_model_unavailable(exc):
                raise model_unavailable(
                    "Requested embedding model is not available.",
                    [
                        {
                            "field": "model",
                            "issue": f"model '{model}' is not available in Ollama",
                        },
                    ],
                ) from exc
            raise dependency_unavailable(
                "The AI provider could not create embeddings.",
                [
                    {
                        "field": "ai_mode",
                        "issue": (
                            f"provider returned HTTP {exc.response.status_code}"
                            if exc.response.status_code > 0
                            else "provider rejected the embed request"
                        ),
                    },
                ],
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise bad_gateway(
                "The AI provider returned a malformed embedding response.",
                [{"field": "ai_mode", "issue": "provider response body was malformed"}],
            ) from exc

        if len(embeddings) != len(inputs) or not embeddings:
            raise bad_gateway(
                "The AI provider returned a malformed embedding response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": "provider returned an unexpected embedding count",
                    },
                ],
            )

        dimension = len(embeddings[0])
        if dimension < 1 or dimension > self._settings.max_embed_dimensions:
            raise bad_gateway(
                "The AI provider returned a malformed embedding response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": "provider returned an unsupported vector dimension",
                    },
                ],
            )
        if any(
            len(vector) != dimension
            or any(not math.isfinite(value) for value in vector)
            for vector in embeddings
        ):
            raise bad_gateway(
                "The AI provider returned a malformed embedding response.",
                [
                    {
                        "field": "ai_mode",
                        "issue": "provider returned inconsistent or non-finite vectors",
                    },
                ],
            )

        return ProviderEmbedResult(model=model, embeddings=embeddings)


def _model_is_available(required: str, available: set[str]) -> bool:
    return required in available or (
        ":" not in required and f"{required}:latest" in available
    )


def _is_model_unavailable(exc: httpx.HTTPStatusError) -> bool:
    error_text = _response_error_text(exc)
    lowered = error_text.casefold()
    return "model" in lowered and any(
        fragment in lowered for fragment in ("not found", "pull", "missing")
    )


def _response_error_text(exc: httpx.HTTPStatusError) -> str:
    raw_error = exc.response.text
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
