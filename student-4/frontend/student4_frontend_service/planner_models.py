"""Student 4's view of the shared workflow contract."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from .assistant_models import AssistantResponse, ToolTrace
from .models import StrictModel

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
    available_tools: list[str] = Field(default_factory=list)


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


class PlannerResponse(StrictModel):
    run: Run
    answer: AssistantResponse


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
