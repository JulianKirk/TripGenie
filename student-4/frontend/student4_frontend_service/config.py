from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_BACKEND_URL = "http://student-4-backend:8008"
DEFAULT_AI_TIMEOUT = 210.0


def _backend_url(value: str | None) -> str:
    candidate = DEFAULT_BACKEND_URL if value is None else value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        message = "BACKEND_URL must be a valid HTTP or HTTPS URL."
        raise ValueError(message)
    return candidate


def _timeout(value: str | None, *, name: str, default: float) -> float:
    try:
        timeout = default if value is None else float(value)
    except ValueError as exc:
        message = f"{name} must be a valid number."
        raise ValueError(message) from exc
    if timeout <= 0:
        message = f"{name} must be greater than zero."
        raise ValueError(message)
    return timeout


@dataclass(frozen=True, slots=True)
class Settings:
    backend_url: str = DEFAULT_BACKEND_URL
    backend_timeout: float = 5.0
    ai_timeout: float = DEFAULT_AI_TIMEOUT
    service_name: str = "student-4-frontend"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend_url=_backend_url(os.getenv("BACKEND_URL")),
            backend_timeout=_timeout(
                os.getenv("BACKEND_TIMEOUT"), name="BACKEND_TIMEOUT", default=5.0
            ),
            ai_timeout=_timeout(
                os.getenv("AI_TIMEOUT"), name="AI_TIMEOUT", default=DEFAULT_AI_TIMEOUT
            ),
        )
