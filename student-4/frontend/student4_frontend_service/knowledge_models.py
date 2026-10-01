from __future__ import annotations

from typing import Literal

from pydantic import Field

from .models import StrictModel

ConfidenceCategory = Literal["high", "medium", "low", "insufficient_context"]


class Citation(StrictModel):
    source_id: str
    path: str
    title: str
    section: str
    chunk_id: str
    excerpt: str


class Retrieval(StrictModel):
    requested_top_k: int
    returned_chunks: int
    maximum_score: float | None = None


class KnowledgeResponse(StrictModel):
    status: Literal["answered", "insufficient_context", "disabled", "error"]
    request_id: str
    answer: str | None = None
    confidence_category: ConfidenceCategory | None = None
    citations: list[Citation] = Field(default_factory=list)
    retrieval: Retrieval | None = None
    run_id: str | None = None
    error: str | None = None
