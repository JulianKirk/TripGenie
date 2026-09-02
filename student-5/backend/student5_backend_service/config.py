from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SERVICE_NAME = "student-5-backend"
DEFAULT_API_PREFIX = "/api"
DEFAULT_DATABASE_API_BASE_URL = "http://student-5-database:8007"


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = DEFAULT_SERVICE_NAME
    api_prefix: str = DEFAULT_API_PREFIX
    database_api_base_url: str = DEFAULT_DATABASE_API_BASE_URL

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            service_name=os.getenv(
                "STUDENT5_BACKEND_SERVICE_NAME", DEFAULT_SERVICE_NAME
            ).strip()
            or DEFAULT_SERVICE_NAME,
            api_prefix=os.getenv(
                "STUDENT5_BACKEND_API_PREFIX", DEFAULT_API_PREFIX
            ).rstrip("/")
            or DEFAULT_API_PREFIX,
            database_api_base_url=os.getenv(
                "STUDENT5_BACKEND_DB_API_BASE_URL", DEFAULT_DATABASE_API_BASE_URL
            ).rstrip("/"),
        )