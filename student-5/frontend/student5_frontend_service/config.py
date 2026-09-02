from __future__ import annotations

import os
from dataclasses import dataclass


def _timeout(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "student-5-frontend"
    backend_base_url: str = "http://student-5-backend:8005"
    ai_analysis_timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            service_name=os.getenv(
                "STUDENT5_FRONTEND_SERVICE_NAME", "student-5-frontend"
            ).strip()
            or "student-5-frontend",
            backend_base_url=os.getenv(
                "STUDENT5_FRONTEND_BACKEND_BASE_URL",
                "http://student-5-backend:8005",
            ).rstrip("/"),
            ai_analysis_timeout_seconds=_timeout(
                "STUDENT5_FRONTEND_AI_ANALYSIS_TIMEOUT_SECONDS", 120.0
            ),
        )