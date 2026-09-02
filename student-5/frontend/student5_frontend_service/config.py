from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "student-5-frontend"
    backend_base_url: str = "http://student-5-backend:8005"

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
        )