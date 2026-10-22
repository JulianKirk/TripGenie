"""Student 4's view of the shared workflow contract."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, Field, field_validator

from .assistant_models import AssistantResponse, FinalAction, ToolTrace
from .schemas import ActivitySchedule, StrictModel

RunId = Annotated[str, Field(pattern=r"^magent_[0-9a-f]{12}$")]


class Plan(BaseModel):
    goal: str
    steps: list[str]
    tools_to_use: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class Check(BaseModel):
    name: str
    passed: bool
    blocking: bool
    detail: str


class Review(BaseModel):
    verdict: Literal["approve", "revise", "reject"]
    summary: str
    issues: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class Step(BaseModel):
    agent: Literal["planner", "worker", "reviewer"]
    attempt: int
    status: Literal["completed", "failed"]
    started_at: str | None = None
    duration_ms: int = 0
    ai_run_id: str | None = None
    model: str | None = None
    output: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    tools: list[ToolTrace] = Field(default_factory=list)


class Human(BaseModel):
    decision: Literal["approve", "correct", "partial", "reject"]
    reviewer: str
    notes: str | None = None
    decided_at: str | None = None
    accepted_actions: list[int] = Field(default_factory=list)


class Run(BaseModel):
    run_id: RunId
    feature: str
    task: str
    trip_id: str | None = None
    correlation_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    attempts: int = 0
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    approved_actions: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal[
        "planning",
        "working",
        "reviewing",
        "awaiting_human",
        "completed",
        "rejected",
        "failed",
    ]
    plan: Plan | None = None
    steps: list[Step] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    review: Review | None = None
    result: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    human: Human | None = None
    error: dict[str, str] | None = None


class SavedSelection(StrictModel):
    activity_id: UUID
    trip_id: str
    status: Literal["added", "already_present"]


class SaveError(StrictModel):
    activity_id: UUID
    trip_id: str
    message: str


class SuggestionDecision(StrictModel):
    activity_id: UUID
    decision: Literal["approve", "reject"]
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("notes")
    @classmethod
    def trim_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PlannerResponse(StrictModel):
    run: Run
    answer: AssistantResponse
    saved: list[SavedSelection] = Field(default_factory=list)
    save_errors: list[SaveError] = Field(default_factory=list)
    previous_run_id: RunId | None = None
    item_decisions: list[SuggestionDecision] = Field(default_factory=list)


class PlannerSelection(ActivitySchedule):
    activity_id: UUID


class Decision(StrictModel):
    decision: Literal["approve", "correct", "reject"]
    reviewer: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=1000)
    corrected_result: FinalAction | None = None
    trip_id: str | None = Field(
        default=None, pattern=r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$"
    )
    selections: list[PlannerSelection] | None = Field(default=None, max_length=6)
    item_decisions: list[SuggestionDecision] | None = Field(
        default=None, min_length=1, max_length=6
    )

    @field_validator("selections")
    @classmethod
    def unique_selections(
        cls, value: list[PlannerSelection] | None
    ) -> list[PlannerSelection] | None:
        if value is not None and len({item.activity_id for item in value}) != len(
            value
        ):
            msg = "Select each activity once."
            raise ValueError(msg)
        return value


class Regenerate(StrictModel):
    reviewer: str = Field(min_length=1, max_length=60)
    feedback: str = Field(min_length=1, max_length=1000)
    dismissed_activity_ids: list[UUID] = Field(default_factory=list, max_length=6)

    @field_validator("feedback", "reviewer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            msg = "Must not be blank."
            raise ValueError(msg)
        return value.strip()


class HistoryEvent(BaseModel):
    sequence: int
    run_id: RunId
    at: str
    actor: str
    event: str
    detail: dict[str, Any] = Field(default_factory=dict)


class Evidence(StrictModel):
    run: Run
    history: list[HistoryEvent]
    item_decisions: list[SuggestionDecision] = Field(default_factory=list)
