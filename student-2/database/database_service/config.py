"""Environment-driven settings for the accommodation database service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///student-2/database/accommodation.db"


@dataclass(slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    service_name: str = "student-2-database"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
