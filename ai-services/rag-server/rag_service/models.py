from __future__ import annotations

import re
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

T = TypeVar("T")
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
FeatureName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$"),
]
CorrelationId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=CORRELATION_PATTERN.pattern),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DataEnvelope(StrictModel, Generic[T]):
    data: T


class ErrorDetail(StrictModel):
    field: str
    issue: str


class ErrorBody(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(StrictModel):
    error: ErrorBody


class DependencyStatus(StrictModel):
    status: str
    service: str
    detail: str | None = None
    code: str | None = None


class AiModeHealthPayload(StrictModel):
    status: str
    service: str
    dependencies: dict[str, DependencyStatus]


class IndexStatus(StrictModel):
    status: str
    path: str
    document_count: int = 0
    chunk_count: int = 0
    embedding_model: str | None = None
    dimension: int | None = None
    detail: str | None = None


class HealthDependencies(StrictModel):
    ai_mode: DependencyStatus
    index: IndexStatus


class HealthPayload(StrictModel):
    status: str
    service: str
    dependencies: HealthDependencies


class QueryRequest(StrictModel):
    query: str = Field(min_length=1, max_length=20000)
    feature: FeatureName = "shared"
    top_k: int | None = Field(default=None, ge=1, le=100)
    correlation_id: CorrelationId | None = None

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            message = "must not be blank"
            raise ValueError(message)
        return cleaned


class Citation(StrictModel):
    source_id: str
    path: str
    title: str
    section: str
    chunk_id: str
    excerpt: str


class RetrievalSummary(StrictModel):
    requested_top_k: int
    returned_chunks: int
    maximum_score: float | None


class QueryPayload(StrictModel):
    schema_version: Literal["1"] = "1"
    run_id: str
    correlation_id: CorrelationId
    answer: str
    confidence_category: Literal[
        "high",
        "medium",
        "low",
        "insufficient_context",
    ]
    insufficient_context: bool
    citations: list[Citation]
    retrieval: RetrievalSummary


class SourceSpec(StrictModel):
    source_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]+$",
    )
    path: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=200)
    feature: FeatureName


class SourceManifest(StrictModel):
    schema_version: Literal["1"]
    sources: list[SourceSpec] = Field(min_length=1, max_length=100)

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: list[SourceSpec]) -> list[SourceSpec]:
        identifiers = [source.source_id for source in value]
        paths = [source.path.casefold() for source in value]
        if len(identifiers) != len(set(identifiers)):
            message = "source_id values must be unique"
            raise ValueError(message)
        if len(paths) != len(set(paths)):
            message = "source paths must be unique"
            raise ValueError(message)
        return value


class IngestionPayload(StrictModel):
    schema_version: Literal["1"] = "1"
    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    reused_chunk_count: int
    embedding_model: str
    dimension: int
    manifest_hash: str


class GroundedGeneration(StrictModel):
    answer: str = Field(min_length=1, max_length=10000)
    citation_ids: list[str] = Field(min_length=1, max_length=10)

    @field_validator("citation_ids")
    @classmethod
    def unique_citations(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AiEmbedPayload(StrictModel):
    run_id: str
    correlation_id: str
    model: str
    provider: str
    dimension: int = Field(gt=0)
    embeddings: list[list[float]] = Field(min_length=1)


class AiGeneratePayload(StrictModel):
    run_id: str
    correlation_id: str
    model: str
    provider: str
    response: str
    done: bool
