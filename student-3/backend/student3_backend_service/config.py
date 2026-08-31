from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_DB_BASE_URL = "http://student-3-database:8004"
DEFAULT_TRIPS_BASE_URL = "http://student-1-backend:8001"


def _parse_timeout(value: str | None, *, env_name: str, default: float) -> float:
    if value is None:
        return default

    try:
        timeout = float(value)
    except ValueError as exc:
        message = f"{env_name} must be a valid number."
        raise ValueError(message) from exc

    if timeout <= 0:
        message = f"{env_name} must be greater than zero."
        raise ValueError(message)

    return timeout


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalise_prefix(value: str | None, *, env_name: str, default: str) -> str:
    prefix = (value or default).strip()
    if not prefix.startswith("/"):
        message = f"{env_name} must start with '/'."
        raise ValueError(message)

    if prefix != "/" and prefix.endswith("/"):
        prefix = prefix.rstrip("/")

    return prefix or default


def _normalise_base_url(value: str | None, *, env_name: str, default: str) -> str:
    candidate = (value or default).strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        message = f"{env_name} must be a valid HTTP or HTTPS URL."
        raise ValueError(message)

    return candidate


@dataclass(slots=True)
class Settings:
    database_api_base_url: str
    database_api_prefix: str = "/internal"
    api_prefix: str = "/api"
    database_api_timeout_seconds: float = 5.0
    service_name: str = "student-3-backend"
    # Student 1 owns trips. Verifying a trip exists is best-effort: when the
    # lookup is disabled or that service is down, plan entries still work.
    trips_api_base_url: str = DEFAULT_TRIPS_BASE_URL
    trips_api_prefix: str = "/api"
    trips_api_timeout_seconds: float = 5.0
    verify_trip_exists: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_api_base_url=_normalise_base_url(
                os.getenv("STUDENT3_BACKEND_DB_API_BASE_URL"),
                env_name="STUDENT3_BACKEND_DB_API_BASE_URL",
                default=DEFAULT_DB_BASE_URL,
            ),
            database_api_prefix=_normalise_prefix(
                os.getenv("STUDENT3_BACKEND_DB_API_PREFIX"),
                env_name="STUDENT3_BACKEND_DB_API_PREFIX",
                default="/internal",
            ),
            api_prefix=_normalise_prefix(
                os.getenv("STUDENT3_BACKEND_API_PREFIX"),
                env_name="STUDENT3_BACKEND_API_PREFIX",
                default="/api",
            ),
            database_api_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT3_BACKEND_DB_API_TIMEOUT_SECONDS"),
                env_name="STUDENT3_BACKEND_DB_API_TIMEOUT_SECONDS",
                default=5.0,
            ),
            service_name=os.getenv(
                "STUDENT3_BACKEND_SERVICE_NAME",
                "student-3-backend",
            ).strip()
            or "student-3-backend",
            trips_api_base_url=_normalise_base_url(
                os.getenv("STUDENT3_BACKEND_TRIPS_API_BASE_URL"),
                env_name="STUDENT3_BACKEND_TRIPS_API_BASE_URL",
                default=DEFAULT_TRIPS_BASE_URL,
            ),
            trips_api_prefix=_normalise_prefix(
                os.getenv("STUDENT3_BACKEND_TRIPS_API_PREFIX"),
                env_name="STUDENT3_BACKEND_TRIPS_API_PREFIX",
                default="/api",
            ),
            trips_api_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT3_BACKEND_TRIPS_API_TIMEOUT_SECONDS"),
                env_name="STUDENT3_BACKEND_TRIPS_API_TIMEOUT_SECONDS",
                default=5.0,
            ),
            verify_trip_exists=_parse_bool(
                os.getenv("STUDENT3_BACKEND_VERIFY_TRIP_EXISTS"),
                default=False,
            ),
        )
