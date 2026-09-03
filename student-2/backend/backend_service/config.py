"""Environment-driven settings for the accommodation backend service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "http://student-2-database:9001"
DEFAULT_DB_TIMEOUT = 5.0
DEFAULT_ITINERARY_URL = "http://student-1-backend:8001"
DEFAULT_ITINERARY_PREFIX = "/api"
DEFAULT_ITINERARY_TIMEOUT = 5.0
DEFAULT_LOCATION_URL = "http://shared-backend:9100"
DEFAULT_LOCATION_TIMEOUT = 5.0
# A local model answers in seconds, not milliseconds. Nothing waits on this
# request but the person who typed the question.
DEFAULT_AI_MODE_TIMEOUT = 30.0
DEFAULT_AI_MAX_ATTEMPTS = 2


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
    # The shared reference service. Country and city live there, so this is
    # where a place name becomes an id and an id becomes a name again. Reached
    # from here and never from the frontend, same rule as the itinerary
    # service.
    location_url: str = DEFAULT_LOCATION_URL
    location_timeout: float = DEFAULT_LOCATION_TIMEOUT
    # The shared AI-Mode service, which is the only thing in the system that
    # talks to a model. `None` means the ask box is switched off: every other
    # endpoint behaves exactly as before and /health says "not_configured".
    # That is the default so this service still boots with no AI container.
    ai_mode_url: str | None = None
    ai_mode_timeout: float = DEFAULT_AI_MODE_TIMEOUT
    # One retry. The model gets a second go with the reason its first answer
    # was unusable; a third rarely changes the outcome and doubles the wait.
    ai_max_attempts: int = DEFAULT_AI_MAX_ATTEMPTS
    service_name: str = "student-2-backend"

    def __post_init__(self) -> None:
        # The one value worth checking: a zero or negative attempt count makes
        # the search loop silently do nothing. Fail at startup instead.
        if self.ai_max_attempts < 1:
            message = "AI_MAX_ATTEMPTS must be at least 1"
            raise ValueError(message)

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
            location_url=os.environ.get("LOCATION_URL", DEFAULT_LOCATION_URL),
            location_timeout=float(
                os.environ.get("LOCATION_TIMEOUT", DEFAULT_LOCATION_TIMEOUT)
            ),
            # Absent and empty both mean off, because an env file that declares
            # the variable with no value is the ordinary way to disable it.
            ai_mode_url=os.environ.get("AI_MODE_URL") or None,
            ai_mode_timeout=float(
                os.environ.get("AI_MODE_TIMEOUT", DEFAULT_AI_MODE_TIMEOUT)
            ),
            ai_max_attempts=int(
                os.environ.get("AI_MAX_ATTEMPTS", DEFAULT_AI_MAX_ATTEMPTS)
            ),
        )
