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
DEFAULT_RAG_TIMEOUT = 130.0


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
    rag_url: str | None = None
    rag_enabled: bool = False
    rag_timeout: float = DEFAULT_RAG_TIMEOUT
    service_name: str = "student-4-backend"

    def __post_init__(self) -> None:
        for name in ("agent_timeout", "rag_timeout"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                message = f"{name} must be positive and finite"
                raise ValueError(message)
        if self.ai_mode_url is not None:
            self.ai_mode_url = self.ai_mode_url.strip().rstrip("/") or None
        if self.rag_url is not None:
            self.rag_url = self.rag_url.strip().rstrip("/") or None
        for name in ("ai_mode_timeout",):
            if getattr(self, name) <= 0:
                message = f"{name} must be greater than zero"
                raise ValueError(message)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            ai_assistant_prompt_asset=os.environ.get(
                "AI_ASSISTANT_PROMPT_ASSET", DEFAULT_AI_ASSISTANT_PROMPT_ASSET
            ),
            assistant_enabled=_flag("AI_ASSISTANT_ENABLED"),
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
            rag_url=os.environ.get("RAG_URL") or None,
            rag_enabled=_flag("RAG_ENABLED"),
            rag_timeout=float(os.environ.get("RAG_TIMEOUT", DEFAULT_RAG_TIMEOUT)),
        )


def _flag(name: str) -> bool:
    value = os.environ.get(name, "false").lower()
    if value not in {"true", "false", "1", "0"}:
        message = f"{name} must be true or false"
        raise ValueError(message)
    return value in {"true", "1"}
