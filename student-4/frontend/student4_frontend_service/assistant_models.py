from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves the inherited model.

from pydantic import Field

from .models import ActivityDetail, StrictModel


class TextPart(StrictModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=1000)


class ActivityPart(StrictModel):
    type: Literal["activity"]
    activity_id: UUID


Part = Annotated[TextPart | ActivityPart, Field(discriminator="type")]


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
    activities: dict[str, ActivityDetail] = Field(default_factory=dict)
    unavailable_activity_ids: list[str] = Field(default_factory=list)
    tools: list[ToolTrace] = Field(default_factory=list)
    error: str | None = None
    model: str | None = None
    provider: str | None = None
