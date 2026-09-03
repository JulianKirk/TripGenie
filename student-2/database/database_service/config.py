"""Environment-driven settings for the accommodation database service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///student-2/database/accommodation.db"


@dataclass(slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    service_name: str = "student-2-database"
    # Starter rows on an empty database, so a fresh container has something to
    # serve. Off in the tests, which assert on exact counts of rows they
    # created themselves. See seed_data.py.
    seed: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            seed=os.environ.get("SEED_DATA", "1") not in {"0", "false", "False"},
        )
