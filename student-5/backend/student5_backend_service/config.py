from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _url(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be a valid HTTP or HTTPS URL.")
    return value


def _prefix(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/") or default
    if not value.startswith("/"):
        raise ValueError(f"{name} must start with '/'.")
    return value


def _timeout(name: str, default: float = 5.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "student-5-backend"
    api_prefix: str = "/api"
    database_api_base_url: str = "http://student-5-database:8007"
    database_api_prefix: str = "/internal"
    database_api_timeout_seconds: float = 5.0
    trips_api_base_url: str = "http://student-1-backend:8001"
    trips_api_prefix: str = "/api"
    trips_api_timeout_seconds: float = 5.0
    transport_api_base_url: str = "http://student-3-backend:8003"
    transport_api_prefix: str = "/api"
    transport_api_timeout_seconds: float = 5.0
    accommodation_api_base_url: str = "http://student-2-backend:9000"
    accommodation_api_prefix: str = "/accommodation"
    accommodation_api_timeout_seconds: float = 5.0
    ai_mode_base_url: str = "http://ai-mode:8006"
    ai_mode_timeout_seconds: float = 20.0
    ai_prompt_max_chars: int = 12000
    ai_prompt_asset: str = "budget_analysis_v1.md"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            service_name=os.getenv(
                "STUDENT5_BACKEND_SERVICE_NAME", "student-5-backend"
            ).strip()
            or "student-5-backend",
            api_prefix=_prefix("STUDENT5_BACKEND_API_PREFIX", "/api"),
            database_api_base_url=_url(
                "STUDENT5_BACKEND_DB_API_BASE_URL",
                "http://student-5-database:8007",
            ),
            database_api_prefix=_prefix("STUDENT5_BACKEND_DB_API_PREFIX", "/internal"),
            database_api_timeout_seconds=_timeout(
                "STUDENT5_BACKEND_DB_API_TIMEOUT_SECONDS"
            ),
            trips_api_base_url=_url(
                "STUDENT5_BACKEND_TRIPS_API_BASE_URL",
                "http://student-1-backend:8001",
            ),
            trips_api_prefix=_prefix("STUDENT5_BACKEND_TRIPS_API_PREFIX", "/api"),
            trips_api_timeout_seconds=_timeout(
                "STUDENT5_BACKEND_TRIPS_API_TIMEOUT_SECONDS"
            ),
            transport_api_base_url=_url(
                "STUDENT5_BACKEND_TRANSPORT_API_BASE_URL",
                "http://student-3-backend:8003",
            ),
            transport_api_prefix=_prefix(
                "STUDENT5_BACKEND_TRANSPORT_API_PREFIX", "/api"
            ),
            transport_api_timeout_seconds=_timeout(
                "STUDENT5_BACKEND_TRANSPORT_API_TIMEOUT_SECONDS"
            ),
            accommodation_api_base_url=_url(
                "STUDENT5_BACKEND_ACCOMMODATION_API_BASE_URL",
                "http://student-2-backend:9000",
            ),
            accommodation_api_prefix=_prefix(
                "STUDENT5_BACKEND_ACCOMMODATION_API_PREFIX", "/accommodation"
            ),
            accommodation_api_timeout_seconds=_timeout(
                "STUDENT5_BACKEND_ACCOMMODATION_API_TIMEOUT_SECONDS"
            ),
            ai_mode_base_url=_url(
                "STUDENT5_BACKEND_AI_MODE_BASE_URL", "http://ai-mode:8006"
            ),
            ai_mode_timeout_seconds=_timeout(
                "STUDENT5_BACKEND_AI_MODE_TIMEOUT_SECONDS", 20.0
            ),
            ai_prompt_max_chars=_positive_int(
                "STUDENT5_BACKEND_AI_PROMPT_MAX_CHARS", 12000
            ),
            ai_prompt_asset=os.getenv(
                "STUDENT5_BACKEND_AI_PROMPT_ASSET", "budget_analysis_v1.md"
            ).strip(),
        )
