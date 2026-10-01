"""Wire models for grounded activity-knowledge answers from the shared RAG server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .schemas import StrictModel

ConfidenceCategory = Literal["high", "medium", "low", "insufficient_context"]


class KnowledgeRequest(StrictModel):
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            message = "question must not be blank"
            raise ValueError(message)
        return value.strip()


class Citation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    path: str
    title: str
    section: str
    chunk_id: str
    excerpt: str


class Retrieval(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested_top_k: int = Field(ge=0)
    returned_chunks: int = Field(ge=0)
    maximum_score: float | None = None


class RagAnswer(BaseModel):
    """Shared RAG `/query` data, schema version 1."""

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["1"]
    run_id: str
    correlation_id: str
    answer: str
    confidence_category: ConfidenceCategory
    insufficient_context: bool
    citations: list[Citation]
    retrieval: Retrieval


class KnowledgeResponse(StrictModel):
    status: Literal["answered", "insufficient_context", "disabled", "error"]
    request_id: str
    answer: str | None = None
    confidence_category: ConfidenceCategory | None = None
    citations: list[Citation] = Field(default_factory=list)
    retrieval: Retrieval | None = None
    run_id: str | None = None
    error: str | None = None
