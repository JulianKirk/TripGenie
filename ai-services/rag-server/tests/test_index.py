from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from conftest import FakeAiMode, write_manifest
from rag_service.errors import ApiError
from rag_service.index import RagIndex, _chunk_source, _source_path
from rag_service.models import SourceSpec

if TYPE_CHECKING:
    from pathlib import Path


def _source(
    root: Path,
    relative_path: str,
    content: str,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _entry(
    source_id: str,
    path: str,
    *,
    feature: str = "shared",
    title: str | None = None,
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "path": path,
        "title": title or source_id,
        "feature": feature,
    }


def _keyword_vector(text: str) -> list[float]:
    if "student one" in text:
        return [0.8, 0.2]
    if "student two" in text:
        return [0.0, 1.0]
    return [1.0, 0.0]


def test_chunking_is_deterministic_and_heading_aware() -> None:
    source = SourceSpec(
        source_id="guide",
        path="docs/guide.md",
        title="Guide",
        feature="shared",
    )
    content = "# Intro\n" + ("alpha beta gamma " * 20) + "\n# Rules\nFinal rule."

    first = _chunk_source(source, content, max_chars=80, overlap=15)
    second = _chunk_source(source, content, max_chars=80, overlap=15)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len(first) > 2
    assert all(len(chunk.text) <= 80 for chunk in first)
    assert first[0].section == "Intro"
    assert first[-1].section == "Rules"
    assert [chunk.ordinal for chunk in first] == list(range(len(first)))


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.md",
        ".env",
        "data/source.md",
        "docs/source.json",
    ],
)
def test_source_path_rejects_unsafe_locations(
    tmp_path: Path,
    relative_path: str,
) -> None:
    source = SourceSpec(
        source_id="unsafe",
        path=relative_path,
        title="Unsafe",
        feature="shared",
    )

    with pytest.raises(ApiError) as raised:
        _source_path(source, tmp_path)

    assert raised.value.code == "VALIDATION_ERROR"


def test_rebuild_reuses_unchanged_chunks_and_removes_stale_sources(
    settings,
) -> None:
    _source(settings.repository_root, "docs/shared.md", "# Shared\nshared facts")
    _source(
        settings.repository_root,
        "docs/student.md",
        "# Student\nstudent one facts",
    )
    write_manifest(
        settings.manifest_path,
        [
            _entry("shared-guide", "docs/shared.md"),
            _entry("student-guide", "docs/student.md", feature="student-1"),
        ],
    )
    index = RagIndex(settings)
    ai_mode = FakeAiMode(vector_for=_keyword_vector)

    first = asyncio.run(index.rebuild(ai_mode))

    assert first.document_count == 2
    assert first.embedded_chunk_count == 2
    assert first.reused_chunk_count == 0
    write_manifest(
        settings.manifest_path,
        [_entry("shared-guide", "docs/shared.md", title="Updated title")],
    )

    second = asyncio.run(index.rebuild(ai_mode))

    assert second.document_count == 1
    assert second.embedded_chunk_count == 0
    assert second.reused_chunk_count == 1
    assert index.status().document_count == 1
    results = index.search([0.8, 0.2], feature="student-1", limit=10)
    assert [result.source_id for result in results] == ["shared-guide"]
    assert results[0].title == "Updated title"


def test_failed_rebuild_preserves_previous_index(settings) -> None:
    _source(settings.repository_root, "docs/guide.md", "# Guide\nold content")
    write_manifest(
        settings.manifest_path,
        [_entry("guide", "docs/guide.md")],
    )
    index = RagIndex(settings)
    asyncio.run(index.rebuild(FakeAiMode()))
    _source(settings.repository_root, "docs/guide.md", "# Guide\nnew content")
    failure = ApiError(503, "DEPENDENCY_UNAVAILABLE", "AI-Mode unavailable")

    with pytest.raises(ApiError):
        asyncio.run(index.rebuild(FakeAiMode(embed_error=failure)))

    assert index.status().status == "ready"
    results = index.search([1.0, 0.0], feature="shared", limit=1)
    assert "old content" in results[0].text
    assert not list(settings.index_path.parent.glob("rag.tmp-*.sqlite3"))


def test_status_detects_missing_corrupt_and_incompatible_indexes(settings) -> None:
    index = RagIndex(settings)
    assert index.status().status == "missing"
    settings.index_path.write_bytes(b"not a database")
    assert index.status().status == "invalid"
    settings.index_path.unlink()

    _source(settings.repository_root, "docs/guide.md", "# Guide\ncontent")
    write_manifest(
        settings.manifest_path,
        [_entry("guide", "docs/guide.md")],
    )
    asyncio.run(index.rebuild(FakeAiMode()))
    with closing(sqlite3.connect(settings.index_path)) as connection:
        connection.execute(
            "UPDATE metadata SET value = 'other-model' WHERE key = 'embedding_model'"
        )
        connection.commit()
    assert index.status().status == "incompatible"
    with closing(sqlite3.connect(settings.index_path)) as connection:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'embedding_model'",
            (settings.embedding_model,),
        )
        connection.execute("UPDATE chunks SET vector = X'00'")
        connection.commit()
    assert index.status().status == "invalid"


def test_status_distinguishes_empty_index(settings) -> None:
    index = RagIndex(settings)

    index._write_atomic([], [], dimension=2, manifest_hash="empty")

    assert index.status().status == "empty"


def test_rebuild_accepts_unicode_and_duplicate_content_with_stable_ids(
    settings,
) -> None:
    content = "# Cafes\nCafe information for Tokyo and 東京."
    _source(settings.repository_root, "docs/one.md", content)
    _source(settings.repository_root, "docs/two.md", content)
    write_manifest(
        settings.manifest_path,
        [
            _entry("guide-one", "docs/one.md"),
            _entry("guide-two", "docs/two.md"),
        ],
    )
    index = RagIndex(settings)

    first = asyncio.run(index.rebuild(FakeAiMode()))
    first_ids = [
        result.chunk_id
        for result in index.search([1.0, 0.0], feature="shared", limit=10)
    ]
    second = asyncio.run(index.rebuild(FakeAiMode()))
    second_ids = [
        result.chunk_id
        for result in index.search([1.0, 0.0], feature="shared", limit=10)
    ]

    assert first.chunk_count == 2
    assert first_ids == second_ids
    assert len(set(first_ids)) == 2
    assert second.reused_chunk_count == 2


def test_rebuild_rejects_empty_sources_and_malformed_embeddings(settings) -> None:
    _source(settings.repository_root, "docs/empty.md", "")
    write_manifest(
        settings.manifest_path,
        [_entry("empty-guide", "docs/empty.md")],
    )
    index = RagIndex(settings)

    with pytest.raises(ApiError) as empty:
        asyncio.run(index.rebuild(FakeAiMode()))

    _source(settings.repository_root, "docs/one.md", "# One\none")
    _source(settings.repository_root, "docs/two.md", "# Two\ntwo")
    write_manifest(
        settings.manifest_path,
        [
            _entry("guide-one", "docs/one.md"),
            _entry("guide-two", "docs/two.md"),
        ],
    )

    def inconsistent(text: str) -> list[float]:
        return [1.0, 0.0] if "One" in text else [1.0]

    with pytest.raises(ApiError) as malformed:
        asyncio.run(index.rebuild(FakeAiMode(vector_for=inconsistent)))

    assert empty.value.code == "VALIDATION_ERROR"
    assert malformed.value.code == "BAD_GATEWAY"


def test_search_orders_by_cosine_and_filters_other_features(settings) -> None:
    _source(settings.repository_root, "docs/shared.md", "# Shared\nshared facts")
    _source(
        settings.repository_root,
        "docs/student-one.md",
        "# One\nstudent one facts",
    )
    _source(
        settings.repository_root,
        "docs/student-two.md",
        "# Two\nstudent two facts",
    )
    write_manifest(
        settings.manifest_path,
        [
            _entry("shared-guide", "docs/shared.md"),
            _entry("student-one", "docs/student-one.md", feature="student-1"),
            _entry("student-two", "docs/student-two.md", feature="student-2"),
        ],
    )
    index = RagIndex(settings)
    asyncio.run(index.rebuild(FakeAiMode(vector_for=_keyword_vector)))

    results = index.search([1.0, 0.0], feature="student-1", limit=10)

    assert [result.source_id for result in results] == [
        "shared-guide",
        "student-one",
    ]
    assert results[0].score > results[1].score

    with pytest.raises(ApiError) as incompatible:
        index.search([1.0], feature="student-1", limit=10)

    assert incompatible.value.code == "BAD_GATEWAY"
