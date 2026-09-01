"""Environment-driven settings for the shared reference database service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///shared/database/location.db"


@dataclass(slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    service_name: str = "shared-database"
    # Starter rows on an empty database. Unlike a per-student service this one
    # is not demo data: every other service's seeded rows point at these ids,
    # so an unseeded shared database leaves them unnameable. Off in the tests,
    # which assert on exact counts of rows they created themselves.
    seed: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            seed=os.environ.get("SEED_DATA", "1") not in {"0", "false", "False"},
        )
