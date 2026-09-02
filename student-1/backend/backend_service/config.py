from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


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


@dataclass(slots=True)
class Settings:
    database_api_base_url: str
    database_api_prefix: str = "/internal"
    api_prefix: str = "/api"
    database_api_timeout_seconds: float = 5.0
    service_name: str = "student-1-backend"
    # Student 2's public API. A trip stores accommodation ids; the names and
    # nightly rates come from there.
    accommodation_api_base_url: str = "http://student-2-backend:9000"
    accommodation_api_timeout_seconds: float = 5.0
    ollama_base_url: str | None = None

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
            ollama_base_url=_normalise_optional_base_url(
                os.getenv("STUDENT1_BACKEND_OLLAMA_BASE_URL"),
                env_name="STUDENT1_BACKEND_OLLAMA_BASE_URL",
            ),
        )
