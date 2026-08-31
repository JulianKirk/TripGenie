from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .config import (
    MAX_CORRELATION_ID_CHARS,
    MAX_METADATA_ITEMS,
    MAX_METADATA_VALUE_CHARS,
    MAX_MODEL_NAME_CHARS,
    MAX_PROMPT_CHARS_HARD_LIMIT,
)

T = TypeVar("T")

ModelName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARS,
        pattern=r"^[A-Za-z0-9._:/-]+$",
    ),
]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(max_length=2000)]
MetadataKey = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
]
MetadataValue = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_METADATA_VALUE_CHARS),
]
PromptText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_PROMPT_CHARS_HARD_LIMIT),
]
CorrelationId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_CORRELATION_ID_CHARS),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorDetail(StrictModel):
    field: str
    issue: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(StrictModel):
    error: ErrorBody


class DataEnvelope(StrictModel, Generic[T]):
    data: T


class DependencyStatus(StrictModel):
    status: ShortText
    service: ShortText
    detail: LongText | None = None
    code: ShortText | None = None


class HealthDependencies(StrictModel):
    ollama: DependencyStatus


class HealthResponse(StrictModel):
    status: ShortText
    service: ShortText
    dependencies: HealthDependencies


class GenerateRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    prompt: PromptText
    model: ModelName | None = None
    output_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    correlation_id: CorrelationId | None = None
    metadata: dict[MetadataKey, MetadataValue] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        if len(value) > MAX_METADATA_ITEMS:
            raise ValueError(f"must contain at most {MAX_METADATA_ITEMS} entries")
        return value


class GenerateResponsePayload(StrictModel):
    run_id: ShortText
    correlation_id: CorrelationId
    model: ModelName
    provider: ShortText = "ollama"
    response: str
    done: bool = True
