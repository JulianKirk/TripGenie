from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_BACKEND_BASE_URL = "http://student-3-backend:8003"


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
    backend_base_url: str
    backend_api_prefix: str = "/api"
    backend_timeout_seconds: float = 5.0
    # Only the AI suggestion route waits this long. It has to clear the
    # backend's own AI budget, which in turn clears AI-Mode's 90s: a local
    # 8b model answering a cold prompt spends ~11s loading off disk before
    # it starts generating.
    ai_timeout_seconds: float = 150.0
    service_name: str = "student-3-frontend"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend_base_url=_normalise_base_url(
                os.getenv("STUDENT3_FRONTEND_BACKEND_BASE_URL"),
                env_name="STUDENT3_FRONTEND_BACKEND_BASE_URL",
                default=DEFAULT_BACKEND_BASE_URL,
            ),
            backend_api_prefix=_normalise_prefix(
                os.getenv("STUDENT3_FRONTEND_BACKEND_API_PREFIX"),
                env_name="STUDENT3_FRONTEND_BACKEND_API_PREFIX",
                default="/api",
            ),
            backend_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT3_FRONTEND_BACKEND_TIMEOUT_SECONDS"),
                env_name="STUDENT3_FRONTEND_BACKEND_TIMEOUT_SECONDS",
                default=5.0,
            ),
            ai_timeout_seconds=_parse_timeout(
                os.getenv("STUDENT3_FRONTEND_AI_TIMEOUT_SECONDS"),
                env_name="STUDENT3_FRONTEND_AI_TIMEOUT_SECONDS",
                default=150.0,
            ),
            service_name=os.getenv(
                "STUDENT3_FRONTEND_SERVICE_NAME",
                "student-3-frontend",
            ).strip()
            or "student-3-frontend",
        )
