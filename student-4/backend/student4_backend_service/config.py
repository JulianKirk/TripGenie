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
DEFAULT_AI_MODE_TIMEOUT = 100.0
DEFAULT_AI_PROMPT_MAX_CHARS = 12_000
DEFAULT_AI_MAX_CANDIDATES = 20
DEFAULT_AI_PLAN_PROMPT_ASSET = "activity_search_plan_v1.md"
DEFAULT_AI_EVALUATION_PROMPT_ASSET = "activity_recommendations_v1.md"


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
    ai_prompt_max_chars: int = DEFAULT_AI_PROMPT_MAX_CHARS
    ai_max_candidates: int = DEFAULT_AI_MAX_CANDIDATES
    ai_plan_prompt_asset: str = DEFAULT_AI_PLAN_PROMPT_ASSET
    ai_evaluation_prompt_asset: str = DEFAULT_AI_EVALUATION_PROMPT_ASSET
    service_name: str = "student-4-backend"

    def __post_init__(self) -> None:
        if self.ai_mode_url is not None:
            self.ai_mode_url = self.ai_mode_url.strip().rstrip("/") or None
        for name in ("ai_mode_timeout", "ai_prompt_max_chars", "ai_max_candidates"):
            if getattr(self, name) <= 0:
                message = f"{name} must be greater than zero"
                raise ValueError(message)

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
            ai_mode_url=os.environ.get("AI_MODE_URL") or None,
            ai_mode_timeout=float(
                os.environ.get("AI_MODE_TIMEOUT", DEFAULT_AI_MODE_TIMEOUT)
            ),
            ai_prompt_max_chars=int(
                os.environ.get("AI_PROMPT_MAX_CHARS", DEFAULT_AI_PROMPT_MAX_CHARS)
            ),
            ai_max_candidates=int(
                os.environ.get("AI_MAX_CANDIDATES", DEFAULT_AI_MAX_CANDIDATES)
            ),
            ai_plan_prompt_asset=os.environ.get(
                "AI_PLAN_PROMPT_ASSET", DEFAULT_AI_PLAN_PROMPT_ASSET
            ),
            ai_evaluation_prompt_asset=os.environ.get(
                "AI_EVALUATION_PROMPT_ASSET", DEFAULT_AI_EVALUATION_PROMPT_ASSET
            ),
        )
