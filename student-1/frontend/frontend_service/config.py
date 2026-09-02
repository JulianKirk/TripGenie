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


@dataclass(slots=True)
class Settings:
    backend_base_url: str
    backend_api_prefix: str = "/api"
    backend_timeout_seconds: float = 5.0
    service_name: str = "student-1-frontend"
    # Where a browser -- not this container -- reaches student 2's webpage. A
    # row on the trip page links there, so it has to be the address on the
    # user's machine, not the compose hostname this service would use.
    accommodation_ui_url: str = "http://localhost:9003"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend_base_url=_normalise_base_url(
                os.getenv(
                    "STUDENT1_FRONTEND_BACKEND_BASE_URL",
                    "http://student-1-backend:8001",
                ),
                env_name="STUDENT1_FRONTEND_BACKEND_BASE_URL",
                default="http://student-1-backend:8001",
            ),
            accommodation_ui_url=_normalise_base_url(
                os.getenv(
                    "STUDENT1_FRONTEND_ACCOMMODATION_UI_URL",
                    "http://localhost:9003",
                ),
                env_name="STUDENT1_FRONTEND_ACCOMMODATION_UI_URL",
                default="http://localhost:9003",
            ),
            backend_api_prefix=_normalise_prefix(
                os.getenv("STUDENT1_FRONTEND_BACKEND_API_PREFIX"),
                env_name="STUDENT1_FRONTEND_BACKEND_API_PREFIX",
                default="/api",
            ),
            backend_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT1_FRONTEND_BACKEND_TIMEOUT_SECONDS"),
                env_name="STUDENT1_FRONTEND_BACKEND_TIMEOUT_SECONDS",
                default=5.0,
            ),
            service_name=os.getenv(
                "STUDENT1_FRONTEND_SERVICE_NAME",
                "student-1-frontend",
            ).strip()
            or "student-1-frontend",
        )
