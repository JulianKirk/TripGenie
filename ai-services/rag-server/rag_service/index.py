from __future__ import annotations

import hashlib
import math
import sqlite3
import struct
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import ValidationError

from .errors import bad_gateway, index_not_ready, validation_error
from .models import IndexStatus, IngestionPayload, SourceManifest, SourceSpec

if TYPE_CHECKING:
    from .ai_mode_client import AiModeClient
    from .config import Settings

SCHEMA_VERSION = "1"
ALLOWED_SOURCE_SUFFIXES = {".md", ".txt"}
DISALLOWED_PARTS = {".git", ".venv", "node_modules", "__pycache__", "data", "logs"}
INCOMPATIBLE_EMBED_MESSAGE = "AI-Mode returned an incompatible query embedding."
UNEXPECTED_MODEL_MESSAGE = "AI-Mode used an unexpected embedding model."
CHANGED_DIMENSION_MESSAGE = "AI-Mode changed embedding dimensions during ingestion."
INCONSISTENT_DIMENSION_MESSAGE = "AI-Mode returned an inconsistent embedding dimension."


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    source_id: str
    path: str
    title: str
    feature: str
    section: str
    ordinal: int
    text: str
    vector: list[float] | None = None


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    source_id: str
    path: str
    title: str
    feature: str
    section: str
    text: str
    score: float


@dataclass(slots=True)
class PreparedCorpus:
    documents: list[tuple[SourceSpec, str]]
    chunks: list[Chunk]
    reused_count: int


class RagIndex:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = settings.index_path

    def status(self) -> IndexStatus:
        if not self._path.exists():
            return IndexStatus(
                status="missing",
                path=str(self._path),
                detail="The RAG index has not been built.",
            )
        try:
            with closing(sqlite3.connect(self._path)) as connection:
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
                chunk_count = connection.execute(
                    "SELECT COUNT(*) FROM chunks"
                ).fetchone()[0]
                vectors = [
                    row[0] for row in connection.execute("SELECT vector FROM chunks")
                ]
        except (sqlite3.Error, KeyError, ValueError) as exc:
            return IndexStatus(
                status="invalid",
                path=str(self._path),
                detail=f"The RAG index is invalid: {type(exc).__name__}.",
            )

        model = metadata.get("embedding_model")
        dimension_text = metadata.get("dimension")
        if (
            metadata.get("schema_version") != SCHEMA_VERSION
            or model != self._settings.embedding_model
            or not dimension_text
        ):
            return IndexStatus(
                status="incompatible",
                path=str(self._path),
                document_count=document_count,
                chunk_count=chunk_count,
                embedding_model=model,
                detail="The RAG index schema or embedding model is incompatible.",
            )
        try:
            dimension = int(dimension_text)
        except ValueError:
            return IndexStatus(
                status="invalid",
                path=str(self._path),
                document_count=document_count,
                chunk_count=chunk_count,
                embedding_model=model,
                detail="The RAG index vector dimension is invalid.",
            )
        try:
            vectors_valid = dimension > 0 and all(
                len(vector) == dimension
                and all(math.isfinite(value) for value in vector)
                for vector in map(_unpack_vector, vectors)
            )
        except (TypeError, ValueError):
            vectors_valid = False
        if not vectors_valid:
            return IndexStatus(
                status="invalid",
                path=str(self._path),
                document_count=document_count,
                chunk_count=chunk_count,
                embedding_model=model,
                detail="The RAG index contains invalid vectors.",
            )
        status = "ready" if document_count > 0 and chunk_count > 0 else "empty"
        return IndexStatus(
            status=status,
            path=str(self._path),
            document_count=document_count,
            chunk_count=chunk_count,
            embedding_model=model,
            dimension=dimension,
            detail=None if status == "ready" else "The RAG index contains no chunks.",
        )

    def search(
        self,
        query_vector: list[float],
        *,
        feature: str,
        limit: int,
    ) -> list[SearchResult]:
        status = self.status()
        if status.status != "ready" or status.dimension is None:
            raise index_not_ready(status.detail or "The RAG index is not ready.")
        if len(query_vector) != status.dimension:
            raise bad_gateway(
                INCOMPATIBLE_EMBED_MESSAGE,
                field="embedding",
                issue=(
                    f"expected dimension {status.dimension}, got {len(query_vector)}"
                ),
            )

        with closing(sqlite3.connect(self._path)) as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, source_id, path, title, feature, section, text, vector
                FROM chunks
                WHERE feature IN ('shared', ?)
                """,
                (feature,),
            ).fetchall()

        results = [
            SearchResult(
                chunk_id=row[0],
                source_id=row[1],
                path=row[2],
                title=row[3],
                feature=row[4],
                section=row[5],
                text=row[6],
                score=_cosine(query_vector, _unpack_vector(row[7])),
            )
            for row in rows
        ]
        results.sort(key=lambda item: (-item.score, item.chunk_id))
        return results[:limit]

    async def rebuild(
        self,
        ai_mode: AiModeClient,
        *,
        manifest_path: Path | None = None,
    ) -> IngestionPayload:
        manifest_file = (manifest_path or self._settings.manifest_path).resolve()
        try:
            manifest_bytes = manifest_file.read_bytes()
        except OSError as exc:
            raise validation_error(
                [{"field": "manifest", "issue": "source manifest could not be read"}]
            ) from exc
        try:
            manifest = SourceManifest.model_validate_json(manifest_bytes)
        except (ValidationError, ValueError) as exc:
            raise validation_error(
                [{"field": "manifest", "issue": "must match the source contract"}]
            ) from exc

        reusable, prior_dimension = self._load_reusable()
        corpus = self._prepare_corpus(manifest, reusable)
        if not corpus.chunks:
            raise validation_error(
                [{"field": "manifest", "issue": "sources produced no searchable text"}]
            )
        dimension, embedded_count = await self._embed_pending(
            corpus.chunks,
            ai_mode,
            prior_dimension=prior_dimension,
        )
        if dimension is None:
            raise validation_error(
                [{"field": "index", "issue": "could not determine vector dimension"}]
            )

        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        self._write_atomic(
            corpus.documents,
            corpus.chunks,
            dimension=dimension,
            manifest_hash=manifest_hash,
        )
        return IngestionPayload(
            document_count=len(corpus.documents),
            chunk_count=len(corpus.chunks),
            embedded_chunk_count=embedded_count,
            reused_chunk_count=corpus.reused_count,
            embedding_model=self._settings.embedding_model,
            dimension=dimension,
            manifest_hash=manifest_hash,
        )

    def _prepare_corpus(
        self,
        manifest: SourceManifest,
        reusable: dict[tuple[str, str], list[Chunk]],
    ) -> PreparedCorpus:
        documents: list[tuple[SourceSpec, str]] = []
        chunks: list[Chunk] = []
        reused_count = 0
        for source in manifest.sources:
            source_path = _source_path(source, self._settings.repository_root)
            try:
                content = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise validation_error(
                    [
                        {
                            "field": source.source_id,
                            "issue": "source must be readable UTF-8 text",
                        }
                    ]
                ) from exc
            if len(content) > self._settings.max_source_chars:
                raise validation_error(
                    [
                        {
                            "field": source.source_id,
                            "issue": (
                                "source exceeds "
                                f"{self._settings.max_source_chars} characters"
                            ),
                        }
                    ]
                )
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            documents.append((source, content_hash))
            prior = reusable.get((source.source_id, content_hash))
            if prior:
                chunks.extend(
                    Chunk(
                        chunk_id=chunk.chunk_id,
                        source_id=source.source_id,
                        path=source.path,
                        title=source.title,
                        feature=source.feature,
                        section=chunk.section,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        vector=chunk.vector,
                    )
                    for chunk in prior
                )
                reused_count += len(prior)
            else:
                chunks.extend(
                    _chunk_source(
                        source,
                        content,
                        max_chars=self._settings.chunk_chars,
                        overlap=self._settings.chunk_overlap_chars,
                    )
                )
        return PreparedCorpus(documents, chunks, reused_count)

    async def _embed_pending(
        self,
        chunks: list[Chunk],
        ai_mode: AiModeClient,
        *,
        prior_dimension: int | None,
    ) -> tuple[int | None, int]:
        pending = [chunk for chunk in chunks if chunk.vector is None]
        dimension = prior_dimension
        embedded_count = 0
        for offset in range(0, len(pending), self._settings.embed_batch_size):
            batch = pending[offset : offset + self._settings.embed_batch_size]
            response = await ai_mode.embed(
                [chunk.text for chunk in batch],
                correlation_id=f"rag-ingest-{uuid4().hex[:12]}",
            )
            if response.model != self._settings.embedding_model:
                issue = (
                    f"expected {self._settings.embedding_model}, got {response.model}"
                )
                raise bad_gateway(
                    UNEXPECTED_MODEL_MESSAGE,
                    field="model",
                    issue=issue,
                )
            if dimension is not None and dimension != response.dimension:
                issue = f"expected dimension {dimension}, got {response.dimension}"
                raise bad_gateway(
                    CHANGED_DIMENSION_MESSAGE,
                    field="embedding",
                    issue=issue,
                )
            dimension = response.dimension
            for chunk, vector in zip(batch, response.embeddings, strict=True):
                if len(vector) != dimension:
                    issue = f"expected dimension {dimension}, got {len(vector)}"
                    raise bad_gateway(
                        INCONSISTENT_DIMENSION_MESSAGE,
                        field="embedding",
                        issue=issue,
                    )
                chunk.vector = vector
                embedded_count += 1
        return dimension, embedded_count

    def _load_reusable(self) -> tuple[dict[tuple[str, str], list[Chunk]], int | None]:
        if not self._path.exists():
            return {}, None
        try:
            with closing(sqlite3.connect(self._path)) as connection:
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
                if (
                    metadata.get("schema_version") != SCHEMA_VERSION
                    or metadata.get("embedding_model") != self._settings.embedding_model
                ):
                    return {}, None
                dimension = int(metadata["dimension"])
                rows = connection.execute(
                    """
                    SELECT d.source_id, d.content_hash, c.chunk_id, c.path, c.title,
                           c.feature, c.section, c.ordinal, c.text, c.vector
                    FROM documents d
                    JOIN chunks c ON c.source_id = d.source_id
                    ORDER BY c.source_id, c.ordinal
                    """
                ).fetchall()
        except (sqlite3.Error, KeyError, ValueError):
            return {}, None

        reusable: dict[tuple[str, str], list[Chunk]] = {}
        try:
            for row in rows:
                vector = _unpack_vector(row[9])
                if len(vector) != dimension or not all(map(math.isfinite, vector)):
                    return {}, None
                reusable.setdefault((row[0], row[1]), []).append(
                    Chunk(
                        chunk_id=row[2],
                        source_id=row[0],
                        path=row[3],
                        title=row[4],
                        feature=row[5],
                        section=row[6],
                        ordinal=row[7],
                        text=row[8],
                        vector=vector,
                    )
                )
        except (TypeError, ValueError):
            return {}, None
        return reusable, dimension

    def _write_atomic(
        self,
        documents: list[tuple[SourceSpec, str]],
        chunks: list[Chunk],
        *,
        dimension: int,
        manifest_hash: str,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(
            f"{self._path.stem}.tmp-{uuid4().hex}{self._path.suffix}"
        )
        try:
            with closing(sqlite3.connect(temporary)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE documents (
                        source_id TEXT PRIMARY KEY,
                        path TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        feature TEXT NOT NULL,
                        content_hash TEXT NOT NULL
                    );
                    CREATE TABLE chunks (
                        chunk_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL REFERENCES documents(source_id)
                            ON DELETE CASCADE,
                        path TEXT NOT NULL,
                        title TEXT NOT NULL,
                        feature TEXT NOT NULL,
                        section TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        vector BLOB NOT NULL
                    );
                    CREATE INDEX idx_chunks_feature ON chunks(feature);
                    """
                )
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    [
                        ("schema_version", SCHEMA_VERSION),
                        ("embedding_model", self._settings.embedding_model),
                        ("dimension", str(dimension)),
                        ("manifest_hash", manifest_hash),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO documents(
                        source_id, path, title, feature, content_hash
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            source.source_id,
                            source.path,
                            source.title,
                            source.feature,
                            content_hash,
                        )
                        for source, content_hash in documents
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO chunks(
                        chunk_id, source_id, path, title, feature, section,
                        ordinal, text, vector
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.source_id,
                            chunk.path,
                            chunk.title,
                            chunk.feature,
                            chunk.section,
                            chunk.ordinal,
                            chunk.text,
                            _pack_vector(chunk.vector or []),
                        )
                        for chunk in chunks
                    ],
                )
                connection.commit()
            temporary.replace(self._path)
        finally:
            temporary.unlink(missing_ok=True)


def _source_path(source: SourceSpec, repository_root: Path) -> Path:
    if Path(source.path).is_absolute():
        raise validation_error(
            [{"field": source.source_id, "issue": "path must be repository-relative"}]
        )
    resolved = (repository_root / source.path).resolve()
    if not resolved.is_relative_to(repository_root):
        raise validation_error(
            [{"field": source.source_id, "issue": "path escapes the repository"}]
        )
    relative_parts = {
        part.casefold() for part in resolved.relative_to(repository_root).parts
    }
    if (
        resolved.suffix.casefold() not in ALLOWED_SOURCE_SUFFIXES
        or relative_parts & DISALLOWED_PARTS
        or resolved.name.casefold().startswith(".env")
    ):
        raise validation_error(
            [
                {
                    "field": source.source_id,
                    "issue": "path is not an allowed knowledge source",
                }
            ]
        )
    if not resolved.is_file():
        raise validation_error(
            [{"field": source.source_id, "issue": "source file does not exist"}]
        )
    return resolved


def _chunk_source(
    source: SourceSpec,
    content: str,
    *,
    max_chars: int,
    overlap: int,
) -> list[Chunk]:
    sections: list[tuple[str, str]] = []
    heading = source.title
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if line.startswith("#"):
            if text := "\n".join(lines).strip():
                sections.append((heading, text))
            heading = line.lstrip("#").strip() or source.title
            lines = []
        else:
            lines.append(line)
    if text := "\n".join(lines).strip():
        sections.append((heading, text))

    chunks: list[Chunk] = []
    ordinal = 0
    for section, text in sections:
        for piece in _windows(
            f"{section}\n\n{text}", max_chars=max_chars, overlap=overlap
        ):
            digest = hashlib.sha256(piece.encode("utf-8")).hexdigest()[:12]
            chunks.append(
                Chunk(
                    chunk_id=f"{source.source_id}:{ordinal}:{digest}",
                    source_id=source.source_id,
                    path=source.path,
                    title=source.title,
                    feature=source.feature,
                    section=section,
                    ordinal=ordinal,
                    text=piece,
                )
            )
            ordinal += 1
    return chunks


def _windows(text: str, *, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split = text.rfind("\n", start + max_chars // 2, end)
            if split < 0:
                split = text.rfind(" ", start + max_chars // 2, end)
            if split > start:
                end = split
        piece = text[start:end].strip()
        if piece:
            windows.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return windows


def _pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}d", *vector)


def _unpack_vector(payload: bytes) -> list[float]:
    if len(payload) % 8:
        message = "invalid vector payload"
        raise ValueError(message)
    return list(struct.unpack(f"<{len(payload) // 8}d", payload))


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        message = "vector dimensions differ"
        raise ValueError(message)
    numerator = math.fsum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
