from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from rag_service.config import Settings
from rag_service.models import (
    AiEmbedPayload,
    AiGeneratePayload,
    DependencyStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class FakeAiMode:
    def __init__(
        self,
        *,
        vector_for: Callable[[str], list[float]] | None = None,
        generated_response: str = '{"answer":"Grounded answer.","citation_ids":["c1"]}',
        embed_error: Exception | None = None,
    ) -> None:
        self.vector_for = vector_for or (lambda _: [1.0, 0.0])
        self.generated_response = generated_response
        self.embed_error = embed_error
        self.embed_calls: list[tuple[list[str], str]] = []
        self.generate_calls: list[tuple[str, dict[str, object], str]] = []

    async def health(self) -> DependencyStatus:
        return DependencyStatus(
            status="ok",
            service="ai-mode",
            detail="AI-Mode is ready.",
        )

    async def embed(
        self,
        inputs: list[str],
        *,
        correlation_id: str,
    ) -> AiEmbedPayload:
        if self.embed_error:
            raise self.embed_error
        self.embed_calls.append((inputs, correlation_id))
        embeddings = [self.vector_for(value) for value in inputs]
        return AiEmbedPayload(
            run_id="aimode_embed",
            correlation_id=correlation_id,
            model="nomic-embed-text",
            provider="ollama",
            dimension=len(embeddings[0]),
            embeddings=embeddings,
        )

    async def generate(
        self,
        prompt: str,
        schema: dict[str, object],
        *,
        correlation_id: str,
    ) -> AiGeneratePayload:
        self.generate_calls.append((prompt, schema, correlation_id))
        return AiGeneratePayload(
            run_id="aimode_generate",
            correlation_id=correlation_id,
            model="qwen2.5:0.5b",
            provider="ollama",
            response=self.generated_response,
            done=True,
        )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        repository_root=tmp_path,
        index_path=tmp_path / "rag.sqlite3",
        manifest_path=tmp_path / "sources.json",
        chunk_chars=120,
        chunk_overlap_chars=20,
        max_query_chars=100,
        max_context_chars=1000,
        max_answer_chars=200,
        citation_excerpt_chars=60,
    )


def write_manifest(path: Path, sources: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps({"schema_version": "1", "sources": sources}),
        encoding="utf-8",
    )
