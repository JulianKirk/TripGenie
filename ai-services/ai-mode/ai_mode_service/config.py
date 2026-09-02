from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_APPROVED_MODELS = 10
MAX_PROMPT_CHARS_HARD_LIMIT = 20000
MAX_SCHEMA_CHARS_HARD_LIMIT = 12000
MAX_RESPONSE_BYTES_HARD_LIMIT = 65536
MAX_METADATA_ITEMS = 8
MAX_METADATA_VALUE_CHARS = 160
MAX_CORRELATION_ID_CHARS = 64
MAX_MODEL_NAME_CHARS = 120
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _parse_timeout(
    value: str | None,
    *,
    env_name: str,
    default: float,
) -> float:
    if value is None:
        return default

    try:
        timeout = float(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a valid number.") from exc

    if timeout <= 0:
        raise ValueError(f"{env_name} must be greater than zero.")

    return timeout


def _parse_positive_int(
    value: str | None,
    *,
    env_name: str,
    default: int,
) -> int:
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a valid integer.") from exc

    if parsed < 1:
        raise ValueError(f"{env_name} must be at least 1.")

    return parsed


def _normalise_base_url(
    value: str | None,
    *,
    env_name: str,
    default: str,
) -> str:
    candidate = (value or default).strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{env_name} must be a valid HTTP or HTTPS URL.")

    return candidate


def _parse_approved_models(value: str | None) -> tuple[str, ...]:
    raw_models = [
        part.strip()
        for part in (value or "qwen2.5:0.5b,llama3.1:8b").split(",")
    ]
    models = tuple(
        dict.fromkeys(part for part in raw_models if part)
    )
    if not models:
        raise ValueError("AI_MODE_ALLOWED_MODELS must contain at least one model.")
    if len(models) > MAX_APPROVED_MODELS:
        raise ValueError(
            "AI_MODE_ALLOWED_MODELS must contain at most "
            f"{MAX_APPROVED_MODELS} models."
        )
    if any(len(model) > MAX_MODEL_NAME_CHARS for model in models):
        raise ValueError(
            "AI_MODE_ALLOWED_MODELS contains a model name that exceeds "
            f"{MAX_MODEL_NAME_CHARS} characters."
        )

    return models


def _validate_limit(
    value: int,
    *,
    env_name: str,
    hard_limit: int,
) -> int:
    if value > hard_limit:
        raise ValueError(f"{env_name} must be at most {hard_limit}.")

    return value


@dataclass(slots=True)
class Settings:
    service_name: str = "ai-mode"
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    default_model: str = "qwen2.5:0.5b"
    allowed_models: tuple[str, ...] = ("qwen2.5:0.5b", "llama3.1:8b")
    ollama_timeout_seconds: float = 15.0
    max_prompt_chars: int = 12000
    max_schema_chars: int = 8000
    max_response_bytes: int = 16384

    def __post_init__(self) -> None:
        self.max_prompt_chars = _validate_limit(
            self.max_prompt_chars,
            env_name="AI_MODE_MAX_PROMPT_CHARS",
            hard_limit=MAX_PROMPT_CHARS_HARD_LIMIT,
        )
        self.max_schema_chars = _validate_limit(
            self.max_schema_chars,
            env_name="AI_MODE_MAX_SCHEMA_CHARS",
            hard_limit=MAX_SCHEMA_CHARS_HARD_LIMIT,
        )
        self.max_response_bytes = _validate_limit(
            self.max_response_bytes,
            env_name="AI_MODE_MAX_RESPONSE_BYTES",
            hard_limit=MAX_RESPONSE_BYTES_HARD_LIMIT,
        )
        if self.default_model not in self.allowed_models:
            raise ValueError(
                "AI_MODE_DEFAULT_MODEL must also appear in AI_MODE_ALLOWED_MODELS."
            )

    @classmethod
    def from_env(cls) -> "Settings":
        allowed_models = _parse_approved_models(os.getenv("AI_MODE_ALLOWED_MODELS"))
        default_model = (
            os.getenv("AI_MODE_DEFAULT_MODEL", "qwen2.5:0.5b").strip()
            or "qwen2.5:0.5b"
        )
        return cls(
            service_name=os.getenv("AI_MODE_SERVICE_NAME", "ai-mode").strip()
            or "ai-mode",
            ollama_base_url=_normalise_base_url(
                os.getenv("AI_MODE_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
                env_name="AI_MODE_OLLAMA_BASE_URL",
                default=DEFAULT_OLLAMA_BASE_URL,
            ),
            default_model=default_model,
            allowed_models=allowed_models,
            ollama_timeout_seconds=_parse_timeout(
                os.getenv("AI_MODE_TIMEOUT_SECONDS"),
                env_name="AI_MODE_TIMEOUT_SECONDS",
                default=15.0,
            ),
            max_prompt_chars=_parse_positive_int(
                os.getenv("AI_MODE_MAX_PROMPT_CHARS"),
                env_name="AI_MODE_MAX_PROMPT_CHARS",
                default=12000,
            ),
            max_schema_chars=_parse_positive_int(
                os.getenv("AI_MODE_MAX_SCHEMA_CHARS"),
                env_name="AI_MODE_MAX_SCHEMA_CHARS",
                default=8000,
            ),
            max_response_bytes=_parse_positive_int(
                os.getenv("AI_MODE_MAX_RESPONSE_BYTES"),
                env_name="AI_MODE_MAX_RESPONSE_BYTES",
                default=16384,
            ),
        )
