from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_AI_MODE_BASE_URL = "http://127.0.0.1:8006"
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "runs.sqlite3"
DEFAULT_FEATURES = ("student-1", "student-2", "student-3", "student-4", "student-5")
FEATURE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

# AI-Mode's own ceilings (AI_MODE_MAX_PROMPT_CHARS defaults to 12000). Prompts
# are budgeted below them so an oversized stage fails here, with a clear code.
MAX_STAGE_PROMPT_CHARS_HARD_LIMIT = 12000
MAX_RETRIES_HARD_LIMIT = 2


def _parse_float(value: str | None, *, env_name: str, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        message = f"{env_name} must be a valid number."
        raise ValueError(message) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        message = f"{env_name} must be greater than zero."
        raise ValueError(message)
    return parsed


def _parse_int(
    value: str | None,
    *,
    env_name: str,
    default: int,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        message = f"{env_name} must be a whole number."
        raise ValueError(message) from exc
    if parsed < minimum:
        message = f"{env_name} must be at least {minimum}."
        raise ValueError(message)
    if maximum is not None and parsed > maximum:
        message = f"{env_name} must be at most {maximum}."
        raise ValueError(message)
    return parsed


def _parse_base_url(value: str | None, *, env_name: str, default: str) -> str:
    candidate = (value or default).strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        message = f"{env_name} must be a valid HTTP or HTTPS URL."
        raise ValueError(message)
    return candidate


def _parse_features(value: str | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_FEATURES
    features = tuple(item.strip() for item in value.split(",") if item.strip())
    if not features:
        message = "MULTI_AGENT_FEATURES must name at least one feature."
        raise ValueError(message)
    for feature in features:
        if FEATURE_PATTERN.fullmatch(feature) is None:
            message = f"MULTI_AGENT_FEATURES has an invalid name: {feature!r}."
            raise ValueError(message)
    return features


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8013
    service_name: str = "multi-agent-server"
    ai_mode_base_url: str = DEFAULT_AI_MODE_BASE_URL
    # Optional: AI-Mode's own default model is used when unset. When set it
    # must be on AI-Mode's allow-list, which AI-Mode enforces.
    model: str | None = None
    db_path: Path = DEFAULT_DB_PATH
    features: tuple[str, ...] = DEFAULT_FEATURES
    # The Planner and Reviewer make one tool-free AI-Mode call each. The Worker
    # runs AI-Mode's MCP tool loop, whose own budget defaults to 180 s.
    # The Planner reads AI-Mode's feature-scoped MCP catalogue; this deadline
    # includes initial inference and model startup.
    planner_timeout_seconds: float = 90.0
    worker_timeout_seconds: float = 200.0
    reviewer_timeout_seconds: float = 60.0
    # A whole run, including one revision. Past this it is marked failed with
    # the steps it completed, so a stuck model cannot hold a run open forever.
    # Two full Planner → Worker → Reviewer rounds take about 2-4 minutes on
    # llama3.1:8b; the limit covers a revision with a slow or cold model.
    run_timeout_seconds: float = 600.0
    max_revisions: int = 1
    max_active_runs: int = 4
    max_task_chars: int = 500
    max_context_chars: int = 4000
    max_system_chars: int = 6000
    max_schema_chars: int = 6000
    max_stage_prompt_chars: int = 11000
    # Tool names containing these words are treated as writes. The Worker is
    # told never to call them, and a run that did is flagged for the human.
    write_tool_markers: tuple[str, ...] = field(
        default=("create", "update", "delete", "remove", "add", "set"),
    )

    def __post_init__(self) -> None:
        if self.max_stage_prompt_chars > MAX_STAGE_PROMPT_CHARS_HARD_LIMIT:
            message = (
                "MULTI_AGENT_MAX_STAGE_PROMPT_CHARS must be at most "
                f"{MAX_STAGE_PROMPT_CHARS_HARD_LIMIT}."
            )
            raise ValueError(message)
        if self.max_revisions > MAX_RETRIES_HARD_LIMIT:
            message = (
                f"MULTI_AGENT_MAX_REVISIONS must be at most {MAX_RETRIES_HARD_LIMIT}."
            )
            raise ValueError(message)
        stage_budget = (
            self.planner_timeout_seconds
            + self.reviewer_timeout_seconds
            + self.worker_timeout_seconds
        )
        if self.run_timeout_seconds < stage_budget:
            message = (
                "MULTI_AGENT_RUN_TIMEOUT_SECONDS must cover at least one planner, "
                "worker and reviewer stage."
            )
            raise ValueError(message)

    @classmethod
    def from_env(cls) -> Settings:
        model = (os.getenv("MULTI_AGENT_MODEL") or "").strip() or None
        db_path = os.getenv("MULTI_AGENT_DB_PATH")
        return cls(
            host=(os.getenv("MULTI_AGENT_HOST") or "127.0.0.1").strip() or "127.0.0.1",
            port=_parse_int(
                os.getenv("MULTI_AGENT_PORT"),
                env_name="MULTI_AGENT_PORT",
                default=8013,
                maximum=65535,
            ),
            service_name=(
                os.getenv("MULTI_AGENT_SERVICE_NAME") or "multi-agent-server"
            ).strip()
            or "multi-agent-server",
            ai_mode_base_url=_parse_base_url(
                os.getenv("MULTI_AGENT_AI_MODE_URL"),
                env_name="MULTI_AGENT_AI_MODE_URL",
                default=DEFAULT_AI_MODE_BASE_URL,
            ),
            model=model,
            db_path=Path(db_path).expanduser() if db_path else DEFAULT_DB_PATH,
            features=_parse_features(os.getenv("MULTI_AGENT_FEATURES")),
            planner_timeout_seconds=_parse_float(
                os.getenv("MULTI_AGENT_PLANNER_TIMEOUT_SECONDS"),
                env_name="MULTI_AGENT_PLANNER_TIMEOUT_SECONDS",
                default=90.0,
            ),
            worker_timeout_seconds=_parse_float(
                os.getenv("MULTI_AGENT_WORKER_TIMEOUT_SECONDS"),
                env_name="MULTI_AGENT_WORKER_TIMEOUT_SECONDS",
                default=200.0,
            ),
            reviewer_timeout_seconds=_parse_float(
                os.getenv("MULTI_AGENT_REVIEWER_TIMEOUT_SECONDS"),
                env_name="MULTI_AGENT_REVIEWER_TIMEOUT_SECONDS",
                default=60.0,
            ),
            run_timeout_seconds=_parse_float(
                os.getenv("MULTI_AGENT_RUN_TIMEOUT_SECONDS"),
                env_name="MULTI_AGENT_RUN_TIMEOUT_SECONDS",
                default=600.0,
            ),
            max_revisions=_parse_int(
                os.getenv("MULTI_AGENT_MAX_REVISIONS"),
                env_name="MULTI_AGENT_MAX_REVISIONS",
                default=1,
                minimum=0,
            ),
            max_active_runs=_parse_int(
                os.getenv("MULTI_AGENT_MAX_ACTIVE_RUNS"),
                env_name="MULTI_AGENT_MAX_ACTIVE_RUNS",
                default=4,
                maximum=32,
            ),
            max_task_chars=_parse_int(
                os.getenv("MULTI_AGENT_MAX_TASK_CHARS"),
                env_name="MULTI_AGENT_MAX_TASK_CHARS",
                default=500,
                maximum=2000,
            ),
        )
