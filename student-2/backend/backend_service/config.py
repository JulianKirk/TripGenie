"""Environment-driven settings for the accommodation backend service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "http://student-2-database:9001"
DEFAULT_DB_TIMEOUT = 5.0
DEFAULT_ITINERARY_URL = "http://student-1-backend:8001"
DEFAULT_ITINERARY_PREFIX = "/api"
DEFAULT_ITINERARY_TIMEOUT = 5.0


@dataclass(slots=True)
class Settings:
    # The database *service*, not a DSN -- the name matches the API doc's
    # config table. The database service uses the same variable for its SQLite
    # path, so the two containers must not share an env file.
    database_url: str = DEFAULT_DATABASE_URL
    db_timeout: float = DEFAULT_DB_TIMEOUT
    # Student 1's public API -- the only service outside this micro-service
    # that this one calls. Reached from here and never from the frontend, so
    # the frontend keeps talking to exactly one backend.
    itinerary_url: str = DEFAULT_ITINERARY_URL
    itinerary_prefix: str = DEFAULT_ITINERARY_PREFIX
    itinerary_timeout: float = DEFAULT_ITINERARY_TIMEOUT
    service_name: str = "student-2-backend"

    @classmethod
    def from_env(cls) -> Settings:
        # ponytail: no normalisers. Both values come from the compose file, and
        # a bad one fails loudly on the first request. Validate here if this
        # ever takes operator-supplied configuration.
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            db_timeout=float(os.environ.get("DB_TIMEOUT", DEFAULT_DB_TIMEOUT)),
            itinerary_url=os.environ.get("ITINERARY_URL", DEFAULT_ITINERARY_URL),
            itinerary_prefix=os.environ.get(
                "ITINERARY_PREFIX", DEFAULT_ITINERARY_PREFIX
            ),
            itinerary_timeout=float(
                os.environ.get("ITINERARY_TIMEOUT", DEFAULT_ITINERARY_TIMEOUT)
            ),
        )
