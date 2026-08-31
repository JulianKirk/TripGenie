"""Environment-driven settings for the accommodation backend service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "http://student-2-database:9001"
DEFAULT_DB_TIMEOUT = 5.0


@dataclass(slots=True)
class Settings:
    # The database *service*, not a DSN -- the name matches the API doc's
    # config table. The database service uses the same variable for its SQLite
    # path, so the two containers must not share an env file.
    database_url: str = DEFAULT_DATABASE_URL
    db_timeout: float = DEFAULT_DB_TIMEOUT
    service_name: str = "student-2-backend"

    @classmethod
    def from_env(cls) -> Settings:
        # ponytail: no normalisers. Both values come from the compose file, and
        # a bad one fails loudly on the first request. Validate here if this
        # ever takes operator-supplied configuration.
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            db_timeout=float(os.environ.get("DB_TIMEOUT", DEFAULT_DB_TIMEOUT)),
        )
