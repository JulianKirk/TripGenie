"""Environment-driven settings for the user database service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///shared/user/database/user.db"


@dataclass(slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    service_name: str = "shared-user-database"
    # Starter accounts on an empty database, so a fresh container has something
    # to log in with. Off in the tests, which assert on exact counts of rows
    # they created themselves. See seed_data.py.
    seed: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            seed=os.environ.get("SEED_DATA", "1") not in {"0", "false", "False"},
        )
