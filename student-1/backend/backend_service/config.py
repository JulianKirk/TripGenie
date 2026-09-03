from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .ai_contract import (
    AI_MODE_PROMPT_MAX_CHARS_DEFAULT,
    AI_MODE_PROMPT_MAX_CHARS_MAX,
)
from .prompt_assets import validate_prompt_asset

AI_MAX_ATTEMPTS_MIN = 1
AI_MAX_ATTEMPTS_MAX = 10


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


def _normalise_prefix(
    value: str | None,
    *,
    env_name: str,
    default: str,
) -> str:
    prefix = (value or default).strip()
    if not prefix.startswith("/"):
        raise ValueError(f"{env_name} must start with '/'.")

    if prefix != "/" and prefix.endswith("/"):
        prefix = prefix.rstrip("/")

    return prefix or default


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


def _normalise_optional_base_url(
    value: str | None,
    *,
    env_name: str,
) -> str | None:
    if value is None or not value.strip():
        return None

    return _normalise_base_url(value, env_name=env_name, default=value)


def _parse_positive_int(
    value: str | None,
    *,
    env_name: str,
    default: int,
    minimum: int = 1,
) -> int:
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a valid integer.") from exc

    if parsed < minimum:
        raise ValueError(f"{env_name} must be at least {minimum}.")

    return parsed


def _parse_int(
    value: str | None,
    *,
    env_name: str,
    default: int,
) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a valid integer.") from exc


def _validate_ai_max_attempts(value: int) -> int:
    if value < AI_MAX_ATTEMPTS_MIN or value > AI_MAX_ATTEMPTS_MAX:
        raise ValueError(
            "STUDENT1_BACKEND_AI_MAX_ATTEMPTS must be between "
            f"{AI_MAX_ATTEMPTS_MIN} and {AI_MAX_ATTEMPTS_MAX}."
        )

    return value


def _validate_ai_prompt_budget(value: int) -> int:
    if value < 1 or value > AI_MODE_PROMPT_MAX_CHARS_MAX:
        raise ValueError(
            "STUDENT1_BACKEND_AI_MODE_MAX_PROMPT_CHARS must be between "
            f"1 and {AI_MODE_PROMPT_MAX_CHARS_MAX}."
        )

    return value


@dataclass(slots=True)
class Settings:
    database_api_base_url: str
    database_api_prefix: str = "/internal"
    api_prefix: str = "/api"
    database_api_timeout_seconds: float = 5.0
    service_name: str = "student-1-backend"
    # Student 2 owns accommodation names and nightly rates.
    accommodation_api_base_url: str = "http://student-2-backend:9000"
    accommodation_api_timeout_seconds: float = 5.0
    ai_mode_base_url: str | None = None
    ai_mode_timeout_seconds: float = 15.0
    ai_prompt_asset: str = "runtime_ai_suggestions_v1.md"
    ai_mode_max_prompt_chars: int = AI_MODE_PROMPT_MAX_CHARS_DEFAULT
    ai_max_attempts: int = 2
    ai_max_context_items: int = 12

    def __post_init__(self) -> None:
        self.ai_max_attempts = _validate_ai_max_attempts(self.ai_max_attempts)
        self.ai_mode_max_prompt_chars = _validate_ai_prompt_budget(
            self.ai_mode_max_prompt_chars
        )
        self.ai_prompt_asset = validate_prompt_asset(self.ai_prompt_asset)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_api_base_url=_normalise_base_url(
                os.getenv(
                    "STUDENT1_BACKEND_DB_API_BASE_URL",
                    "http://student-1-database:8002",
                ),
                env_name="STUDENT1_BACKEND_DB_API_BASE_URL",
                default="http://student-1-database:8002",
            ),
            accommodation_api_base_url=_normalise_base_url(
                os.getenv(
                    "STUDENT1_BACKEND_ACCOMMODATION_API_BASE_URL",
                    "http://student-2-backend:9000",
                ),
                env_name="STUDENT1_BACKEND_ACCOMMODATION_API_BASE_URL",
                default="http://student-2-backend:9000",
            ),
            accommodation_api_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT1_BACKEND_ACCOMMODATION_API_TIMEOUT_SECONDS"),
                env_name="STUDENT1_BACKEND_ACCOMMODATION_API_TIMEOUT_SECONDS",
                default=5.0,
            ),
            database_api_prefix=_normalise_prefix(
                os.getenv("STUDENT1_BACKEND_DB_API_PREFIX"),
                env_name="STUDENT1_BACKEND_DB_API_PREFIX",
                default="/internal",
            ),
            api_prefix=_normalise_prefix(
                os.getenv("STUDENT1_BACKEND_API_PREFIX"),
                env_name="STUDENT1_BACKEND_API_PREFIX",
                default="/api",
            ),
            database_api_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS"),
                env_name="STUDENT1_BACKEND_DB_API_TIMEOUT_SECONDS",
                default=5.0,
            ),
            service_name=os.getenv(
                "STUDENT1_BACKEND_SERVICE_NAME",
                "student-1-backend",
            ).strip()
            or "student-1-backend",
            ai_mode_base_url=_normalise_optional_base_url(
                os.getenv("STUDENT1_BACKEND_AI_MODE_BASE_URL"),
                env_name="STUDENT1_BACKEND_AI_MODE_BASE_URL",
            ),
            ai_mode_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT1_BACKEND_AI_MODE_TIMEOUT_SECONDS"),
                env_name="STUDENT1_BACKEND_AI_MODE_TIMEOUT_SECONDS",
                default=15.0,
            ),
            ai_prompt_asset=os.getenv(
                "STUDENT1_BACKEND_AI_PROMPT_ASSET",
                "runtime_ai_suggestions_v1.md",
            ).strip()
            or "runtime_ai_suggestions_v1.md",
            ai_mode_max_prompt_chars=_parse_int(
                os.getenv("STUDENT1_BACKEND_AI_MODE_MAX_PROMPT_CHARS"),
                env_name="STUDENT1_BACKEND_AI_MODE_MAX_PROMPT_CHARS",
                default=AI_MODE_PROMPT_MAX_CHARS_DEFAULT,
            ),
            ai_max_attempts=_parse_int(
                os.getenv("STUDENT1_BACKEND_AI_MAX_ATTEMPTS"),
                env_name="STUDENT1_BACKEND_AI_MAX_ATTEMPTS",
                default=2,
            ),
            ai_max_context_items=_parse_positive_int(
                os.getenv("STUDENT1_BACKEND_AI_MAX_CONTEXT_ITEMS"),
                env_name="STUDENT1_BACKEND_AI_MAX_CONTEXT_ITEMS",
                default=12,
            ),
        )
