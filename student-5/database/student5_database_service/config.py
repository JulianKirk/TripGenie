from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "student-5-database"
    api_prefix: str = "/internal"
    sqlite_path: Path = Path("data/student-5/tripgenie.db")
    seed_data: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            service_name=os.getenv(
                "STUDENT5_DB_SERVICE_NAME", "student-5-database"
            ).strip()
            or "student-5-database",
            api_prefix=os.getenv("STUDENT5_DB_API_PREFIX", "/internal").rstrip("/")
            or "/internal",
            sqlite_path=Path(
                os.getenv("STUDENT5_SQLITE_PATH", "data/student-5/tripgenie.db")
            ),
            seed_data=_parse_bool(os.getenv("STUDENT5_SEED_DATA"), default=True),
        )
