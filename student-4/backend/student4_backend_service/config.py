from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "http://student-4-database:8009"
DEFAULT_DB_TIMEOUT = 5.0
DEFAULT_LOCATION_URL = "http://shared-backend:9100"
DEFAULT_LOCATION_TIMEOUT = 5.0
DEFAULT_ITINERARY_URL = "http://student-1-backend:8001"
DEFAULT_ITINERARY_PREFIX = "/api"
DEFAULT_ITINERARY_TIMEOUT = 5.0


@dataclass(slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    db_timeout: float = DEFAULT_DB_TIMEOUT
    location_url: str = DEFAULT_LOCATION_URL
    location_timeout: float = DEFAULT_LOCATION_TIMEOUT
    itinerary_url: str = DEFAULT_ITINERARY_URL
    itinerary_prefix: str = DEFAULT_ITINERARY_PREFIX
    itinerary_timeout: float = DEFAULT_ITINERARY_TIMEOUT
    service_name: str = "student-4-backend"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            db_timeout=float(os.environ.get("DB_TIMEOUT", DEFAULT_DB_TIMEOUT)),
            location_url=os.environ.get("LOCATION_URL", DEFAULT_LOCATION_URL),
            location_timeout=float(
                os.environ.get("LOCATION_TIMEOUT", DEFAULT_LOCATION_TIMEOUT)
            ),
            itinerary_url=os.environ.get("ITINERARY_URL", DEFAULT_ITINERARY_URL),
            itinerary_prefix=os.environ.get(
                "ITINERARY_PREFIX", DEFAULT_ITINERARY_PREFIX
            ),
            itinerary_timeout=float(
                os.environ.get("ITINERARY_TIMEOUT", DEFAULT_ITINERARY_TIMEOUT)
            ),
        )
