from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_AI_MODE_BASE_URL = "http://127.0.0.1:8006"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_PORT = 8011


def _positive_int(value: str | None, *, name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        message = f"{name} must be a valid integer."
        raise ValueError(message) from exc
    if parsed < 1:
        message = f"{name} must be at least 1."
        raise ValueError(message)
    return parsed


def _positive_float(value: str | None, *, name: str, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        message = f"{name} must be a valid number."
        raise ValueError(message) from exc
    if parsed <= 0:
        message = f"{name} must be greater than zero."
        raise ValueError(message)
    return parsed


def _score(value: str | None, *, name: str, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        message = f"{name} must be a valid number."
        raise ValueError(message) from exc
    if not 0 <= parsed <= 1:
        message = f"{name} must be between 0 and 1."
        raise ValueError(message)
    return parsed


def _http_url(value: str | None, *, name: str, default: str) -> str:
    candidate = (value or default).strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        message = f"{name} must be a valid HTTP or HTTPS URL."
        raise ValueError(message)
    return candidate


def _path(value: str | None, *, default: Path) -> Path:
    return Path(value).expanduser().resolve() if value else default.resolve()


@dataclass(slots=True)
class Settings:
    repository_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[3]
    )
    service_name: str = "rag-server"
    bind_host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    ai_mode_base_url: str = DEFAULT_AI_MODE_BASE_URL
    ai_mode_timeout_seconds: float = 120.0
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    index_path: Path | None = None
    manifest_path: Path | None = None
    default_top_k: int = 5
    max_top_k: int = 10
    min_relevance_score: float = 0.35
    medium_relevance_score: float = 0.55
    high_relevance_score: float = 0.75
    max_query_chars: int = 2000
    max_context_chars: int = 12000
    max_answer_chars: int = 4000
    max_source_chars: int = 1_000_000
    chunk_chars: int = 1200
    chunk_overlap_chars: int = 150
    embed_batch_size: int = 16
    citation_excerpt_chars: int = 240

    def __post_init__(self) -> None:
        self.repository_root = self.repository_root.resolve()
        service_root = Path(__file__).resolve().parents[1]
        self.index_path = (
            self.index_path or service_root / "data" / "rag.sqlite3"
        ).resolve()
        self.manifest_path = (
            self.manifest_path or service_root / "config" / "sources.json"
        ).resolve()
        if not 1 <= self.port <= 65535:
            message = "RAG_PORT must be between 1 and 65535."
            raise ValueError(message)
        if self.default_top_k > self.max_top_k:
            message = "RAG_DEFAULT_TOP_K must be at most RAG_MAX_TOP_K."
            raise ValueError(message)
        if not (
            0
            <= self.min_relevance_score
            <= self.medium_relevance_score
            <= self.high_relevance_score
            <= 1
        ):
            message = (
                "RAG relevance thresholds must be ordered minimum <= medium <= high."
            )
            raise ValueError(message)
        if self.chunk_overlap_chars >= self.chunk_chars:
            message = "RAG_CHUNK_OVERLAP_CHARS must be less than RAG_CHUNK_CHARS."
            raise ValueError(message)

    @classmethod
    def from_env(cls) -> Settings:
        repository_root = _path(
            os.getenv("RAG_REPOSITORY_ROOT"),
            default=Path(__file__).resolve().parents[3],
        )
        return cls(
            repository_root=repository_root,
            service_name=os.getenv("RAG_SERVICE_NAME", "rag-server").strip()
            or "rag-server",
            bind_host=os.getenv("RAG_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_positive_int(
                os.getenv("RAG_PORT"),
                name="RAG_PORT",
                default=DEFAULT_PORT,
            ),
            ai_mode_base_url=_http_url(
                os.getenv("RAG_AI_MODE_BASE_URL"),
                name="RAG_AI_MODE_BASE_URL",
                default=DEFAULT_AI_MODE_BASE_URL,
            ),
            ai_mode_timeout_seconds=_positive_float(
                os.getenv("RAG_AI_MODE_TIMEOUT_SECONDS"),
                name="RAG_AI_MODE_TIMEOUT_SECONDS",
                default=120.0,
            ),
            embedding_model=os.getenv(
                "RAG_EMBEDDING_MODEL",
                DEFAULT_EMBEDDING_MODEL,
            ).strip()
            or DEFAULT_EMBEDDING_MODEL,
            index_path=_path(
                os.getenv("RAG_INDEX_PATH"),
                default=Path(__file__).resolve().parents[1] / "data" / "rag.sqlite3",
            ),
            manifest_path=_path(
                os.getenv("RAG_SOURCE_MANIFEST"),
                default=Path(__file__).resolve().parents[1] / "config" / "sources.json",
            ),
            default_top_k=_positive_int(
                os.getenv("RAG_DEFAULT_TOP_K"),
                name="RAG_DEFAULT_TOP_K",
                default=5,
            ),
            max_top_k=_positive_int(
                os.getenv("RAG_MAX_TOP_K"),
                name="RAG_MAX_TOP_K",
                default=10,
            ),
            min_relevance_score=_score(
                os.getenv("RAG_MIN_RELEVANCE_SCORE"),
                name="RAG_MIN_RELEVANCE_SCORE",
                default=0.35,
            ),
            medium_relevance_score=_score(
                os.getenv("RAG_MEDIUM_RELEVANCE_SCORE"),
                name="RAG_MEDIUM_RELEVANCE_SCORE",
                default=0.55,
            ),
            high_relevance_score=_score(
                os.getenv("RAG_HIGH_RELEVANCE_SCORE"),
                name="RAG_HIGH_RELEVANCE_SCORE",
                default=0.75,
            ),
            max_query_chars=_positive_int(
                os.getenv("RAG_MAX_QUERY_CHARS"),
                name="RAG_MAX_QUERY_CHARS",
                default=2000,
            ),
            max_context_chars=_positive_int(
                os.getenv("RAG_MAX_CONTEXT_CHARS"),
                name="RAG_MAX_CONTEXT_CHARS",
                default=12000,
            ),
            max_answer_chars=_positive_int(
                os.getenv("RAG_MAX_ANSWER_CHARS"),
                name="RAG_MAX_ANSWER_CHARS",
                default=4000,
            ),
            max_source_chars=_positive_int(
                os.getenv("RAG_MAX_SOURCE_CHARS"),
                name="RAG_MAX_SOURCE_CHARS",
                default=1_000_000,
            ),
            chunk_chars=_positive_int(
                os.getenv("RAG_CHUNK_CHARS"),
                name="RAG_CHUNK_CHARS",
                default=1200,
            ),
            chunk_overlap_chars=_positive_int(
                os.getenv("RAG_CHUNK_OVERLAP_CHARS"),
                name="RAG_CHUNK_OVERLAP_CHARS",
                default=150,
            ),
            embed_batch_size=_positive_int(
                os.getenv("RAG_EMBED_BATCH_SIZE"),
                name="RAG_EMBED_BATCH_SIZE",
                default=16,
            ),
            citation_excerpt_chars=_positive_int(
                os.getenv("RAG_CITATION_EXCERPT_CHARS"),
                name="RAG_CITATION_EXCERPT_CHARS",
                default=240,
            ),
        )
