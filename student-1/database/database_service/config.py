from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    sqlite_path: Path
    service_name: str = "student-1-database"
    api_prefix: str = "/internal"
    sqlite_timeout_seconds: float = 5.0
    seed_data: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        sqlite_path = Path(
            os.getenv("STUDENT1_SQLITE_PATH", "data/student-1/tripgenie.db"),
        )

        return cls(
            sqlite_path=sqlite_path,
            seed_data=_parse_bool(os.getenv("STUDENT1_SEED_DATA"), default=True),
        )
