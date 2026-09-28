from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves the inherited model.

from pydantic import Field, TypeAdapter, field_validator

from .schemas import Activity, StrictModel


class AssistantRequest(StrictModel):
    question: str = Field(min_length=1, max_length=500)
    trip_id: str | None = Field(
        default=None, pattern=r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$"
    )

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            message = "question must not be blank"
            raise ValueError(message)
        return value.strip()


class TextPart(StrictModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=1000)


class ActivityPart(StrictModel):
    type: Literal["activity"]
    activity_id: UUID


Part = Annotated[TextPart | ActivityPart, Field(discriminator="type")]


class ToolAction(StrictModel):
    type: Literal["tool"]
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class FinalAction(StrictModel):
    type: Literal["final"]
    parts: list[Part] = Field(min_length=1, max_length=12)


Action = Annotated[ToolAction | FinalAction, Field(discriminator="type")]
ACTION: TypeAdapter[Action] = TypeAdapter(Action)


class ToolTrace(StrictModel):
    tool: str
    arguments: dict[str, Any]
    status: Literal["success", "error", "rejected"]
    duration_ms: int = Field(ge=0)
    correlation_id: str | None = None
    result_count: int | None = None
    activity_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class AssistantResponse(StrictModel):
    status: Literal["complete", "error"] = "error"
    request_id: str
    parts: list[Part] = Field(default_factory=list)
    activities: dict[str, Activity] = Field(default_factory=dict)
    unavailable_activity_ids: list[str] = Field(default_factory=list)
    tools: list[ToolTrace] = Field(default_factory=list)
    error: str | None = None
    model: str | None = None
    provider: str | None = None
