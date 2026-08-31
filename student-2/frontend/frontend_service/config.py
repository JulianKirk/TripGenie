"""Environment-driven settings for the accommodation frontend service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BACKEND_URL = "http://student-2-backend:9000"
DEFAULT_BACKEND_TIMEOUT = 5.0


@dataclass(slots=True)
class Settings:
    # The backend *service*, the only thing this service talks to. It never
    # reaches the database service -- that is the backend's alone.
    backend_url: str = DEFAULT_BACKEND_URL
    backend_timeout: float = DEFAULT_BACKEND_TIMEOUT
    service_name: str = "student-2-frontend"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend_url=os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL),
            backend_timeout=float(
                os.environ.get("BACKEND_TIMEOUT", DEFAULT_BACKEND_TIMEOUT)
            ),
        )
