from __future__ import annotations

import math
import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "http://student-4-database:8009"
DEFAULT_DB_TIMEOUT = 5.0
DEFAULT_LOCATION_URL = "http://shared-backend:9100"
DEFAULT_LOCATION_TIMEOUT = 5.0
DEFAULT_ITINERARY_URL = "http://student-1-backend:8001"
DEFAULT_ITINERARY_PREFIX = "/api"
DEFAULT_ITINERARY_TIMEOUT = 5.0
DEFAULT_AI_MODE_TIMEOUT = 100.0
DEFAULT_AI_ASSISTANT_PROMPT_ASSET = "activity_assistant_v1.md"


@dataclass(slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    db_timeout: float = DEFAULT_DB_TIMEOUT
    location_url: str = DEFAULT_LOCATION_URL
    location_timeout: float = DEFAULT_LOCATION_TIMEOUT
    itinerary_url: str = DEFAULT_ITINERARY_URL
    itinerary_prefix: str = DEFAULT_ITINERARY_PREFIX
    itinerary_timeout: float = DEFAULT_ITINERARY_TIMEOUT
    ai_mode_url: str | None = None
    ai_mode_timeout: float = DEFAULT_AI_MODE_TIMEOUT
    ai_assistant_prompt_asset: str = DEFAULT_AI_ASSISTANT_PROMPT_ASSET
    assistant_enabled: bool = False
    agent_timeout: float = 210.0
    service_name: str = "student-4-backend"

    def __post_init__(self) -> None:
        for name in ("agent_timeout",):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                message = f"{name} must be positive and finite"
                raise ValueError(message)
        if self.ai_mode_url is not None:
            self.ai_mode_url = self.ai_mode_url.strip().rstrip("/") or None
        for name in ("ai_mode_timeout",):
            if getattr(self, name) <= 0:
                message = f"{name} must be greater than zero"
                raise ValueError(message)

    @classmethod
    def from_env(cls) -> Settings:
        enabled = os.environ.get("AI_ASSISTANT_ENABLED", "false").lower()
        if enabled not in {"true", "false", "1", "0"}:
            message = "AI_ASSISTANT_ENABLED must be true or false"
            raise ValueError(message)
        return cls(
            ai_assistant_prompt_asset=os.environ.get(
                "AI_ASSISTANT_PROMPT_ASSET", DEFAULT_AI_ASSISTANT_PROMPT_ASSET
            ),
            assistant_enabled=enabled in {"true", "1"},
            agent_timeout=float(os.environ.get("AGENT_TIMEOUT", "210")),
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
            ai_mode_url=os.environ.get("AI_MODE_URL") or None,
            ai_mode_timeout=float(
                os.environ.get("AI_MODE_TIMEOUT", DEFAULT_AI_MODE_TIMEOUT)
            ),
        )
