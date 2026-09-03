"""Environment-driven settings for the Student 4 database service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///student-4/database/activities.db"


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    message = "SEED_DATA must be a boolean value"
    raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    seed: bool = True
    service_name: str = "student-4-database"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            seed=_as_bool(os.environ.get("SEED_DATA"), default=True),
        )
