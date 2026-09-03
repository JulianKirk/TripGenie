"""Environment-driven settings for the accommodation frontend service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BACKEND_URL = "http://student-2-backend:9000"
DEFAULT_BACKEND_TIMEOUT = 5.0
# The ask box waits on a language model, and a local one on a laptop answers in
# tens of seconds, not in the 5 the rest of the page allows. Big enough for the
# backend's own worst case -- its AI_MODE_TIMEOUT times AI_MAX_ATTEMPTS, plus
# the ordinary search after it -- so the page gives up only once the backend
# already has. docker-compose.yml sets all three together; this default matches
# what it sets.
#
# ponytail: one extra number, not a second client. The 5s stays where it
# belongs: a slow ordinary search is a broken backend, and the page should say
# so quickly.
DEFAULT_AI_TIMEOUT = 210.0


@dataclass(slots=True)
class Settings:
    # The backend *service*, the only thing this service talks to. It never
    # reaches the database service -- that is the backend's alone.
    backend_url: str = DEFAULT_BACKEND_URL
    backend_timeout: float = DEFAULT_BACKEND_TIMEOUT
    ai_timeout: float = DEFAULT_AI_TIMEOUT
    service_name: str = "student-2-frontend"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend_url=os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL),
            backend_timeout=float(
                os.environ.get("BACKEND_TIMEOUT", DEFAULT_BACKEND_TIMEOUT)
            ),
            ai_timeout=float(os.environ.get("AI_TIMEOUT", DEFAULT_AI_TIMEOUT)),
        )
