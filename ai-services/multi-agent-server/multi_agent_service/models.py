"""Wire contracts for the Multi-Agent Server.

`ToolTrace` is AI-Mode's own trace shape, passed through unchanged, so every
feature's existing grounding code and templates keep working against it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

T = TypeVar("T")

CORRELATION_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$"
TOOL_NAME = r"^[a-z][a-z0-9_]{0,63}$"
# `items[].id`, `suggestions[].transport_id`, `answer`: dotted keys, where a
# trailing [] walks every element of a list.
ID_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\[\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[\])?)*$"
)

RunStatus = Literal[
    "planning",
    "working",
    "reviewing",
    "awaiting_human",
    "completed",
    "rejected",
    "failed",
]
ACTIVE_STATUSES = frozenset({"planning", "working", "reviewing"})
TERMINAL_STATUSES = frozenset({"completed", "rejected", "failed"})
AgentName = Literal["planner", "worker", "reviewer"]
Verdict = Literal["approve", "revise", "reject"]
Decision = Literal["approve", "correct", "partial", "reject"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LenientModel(BaseModel):
    """For shapes another service owns: new fields there must not break us."""

    model_config = ConfigDict(extra="ignore")


class DataEnvelope(StrictModel, Generic[T]):
    data: T


class ErrorDetail(StrictModel):
    field: str
    issue: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(StrictModel):
    error: ErrorBody


# --------------------------------------------------------------------- request


class Grounding(StrictModel):
    """Where the Worker's result names records, and whose tools may back them.

    Every value found at `id_paths` must have been returned by a successful
    tool result whose `source` is `source`, during this run.
    """

    source: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    id_paths: list[str] = Field(default_factory=list, max_length=8)
    id_keys: list[
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")]
    ] = Field(default_factory=lambda: ["id"], min_length=1, max_length=4)

    @field_validator("id_paths")
    @classmethod
    def validate_paths(cls, value: list[str]) -> list[str]:
        for path in value:
            if ID_PATH.fullmatch(path) is None:
                message = f"invalid id path {path!r}"
                raise ValueError(message)
        return value


class RunRequest(StrictModel):
    """What a feature backend (or the CLI) sends to start a workflow."""

    feature: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
    task: Annotated[str, StringConstraints(min_length=1)]
    trip_id: (
        Annotated[
            str,
            StringConstraints(pattern=r"^trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}$"),
        ]
        | None
    ) = None
    context: dict[str, Any] = Field(default_factory=dict)
    feature_instructions: str = ""
    worker_system: Annotated[str, StringConstraints(min_length=1)]
    output_schema: dict[str, Any]
    allowed_tools: list[Annotated[str, StringConstraints(pattern=TOOL_NAME)]] = Field(
        default_factory=list,
        max_length=24,
    )
    grounding: Grounding | None = None
    # Where the Worker's result lists changes the human may approve, e.g.
    # `actions`. The server never performs them; the feature backend does,
    # through its own routes, only after the human decision.
    actions_path: str | None = None
    correlation_id: Annotated[str, StringConstraints(pattern=CORRELATION_ID)] | None = (
        None
    )
    metadata: dict[
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,40}$")],
        Annotated[str, StringConstraints(max_length=160)],
    ] = Field(default_factory=dict, max_length=6)

    @field_validator("allowed_tools")
    @classmethod
    def distinct_tools(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            message = "must not repeat a tool"
            raise ValueError(message)
        return value

    @field_validator("actions_path")
    @classmethod
    def validate_actions_path(cls, value: str | None) -> str | None:
        if value is not None and ID_PATH.fullmatch(value) is None:
            message = "must be a dotted path such as 'actions'"
            raise ValueError(message)
        return value

    @field_validator("output_schema")
    @classmethod
    def object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            message = "must be a JSON schema whose type is 'object'"
            raise ValueError(message)
        return value


class ReviewRequest(StrictModel):
    """The human's decision on a run that is awaiting review."""

    decision: Decision
    reviewer: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    notes: Annotated[str, StringConstraints(max_length=1000)] | None = None
    # `correct`: the human's corrected result, validated against the run's
    # output schema. `partial`: indexes of the proposed actions accepted.
    corrected_result: dict[str, Any] | None = None
    accepted_actions: list[Annotated[int, Field(ge=0)]] | None = None


# ------------------------------------------------------------- agent outputs


class Plan(StrictModel):
    goal: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    steps: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = (
        Field(min_length=1, max_length=8)
    )
    required_evidence: list[
        Annotated[str, StringConstraints(min_length=1, max_length=300)]
    ] = Field(default_factory=list, max_length=8)
    tools_to_use: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        default_factory=list,
        max_length=8,
    )
    success_criteria: list[
        Annotated[str, StringConstraints(min_length=1, max_length=300)]
    ] = Field(default_factory=list, max_length=6)


class AgentReview(StrictModel):
    verdict: Verdict
    summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    issues: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = (
        Field(default_factory=list, max_length=8)
    )
    risks: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = (
        Field(default_factory=list, max_length=8)
    )
    recommendations: list[
        Annotated[str, StringConstraints(min_length=1, max_length=300)]
    ] = Field(default_factory=list, max_length=8)


# ------------------------------------------------------------------ run record


class ToolTrace(LenientModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str = "error"
    duration_ms: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None


class Check(StrictModel):
    name: str
    passed: bool
    blocking: bool
    detail: str


class Step(StrictModel):
    agent: AgentName
    attempt: int
    status: Literal["completed", "failed"]
    started_at: datetime
    duration_ms: int
    ai_run_id: str | None = None
    model: str | None = None
    output: dict[str, Any] | None = None
    tools: list[ToolTrace] = Field(default_factory=list)
    error: dict[str, str] | None = None


class HumanReview(StrictModel):
    decision: Decision
    reviewer: str
    notes: str | None = None
    decided_at: datetime
    accepted_actions: list[int] = Field(default_factory=list)


class RunRecord(StrictModel):
    run_id: str
    feature: str
    task: str
    trip_id: str | None = None
    correlation_id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    attempts: int = 0
    plan: Plan | None = None
    steps: list[Step] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    review: AgentReview | None = None
    # The Worker's result as reviewed, then the result the human signed off.
    result: dict[str, Any] | None = None
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    human: HumanReview | None = None
    final_result: dict[str, Any] | None = None
    approved_actions: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, str] | None = None


class StoredRun(RunRecord):
    """A run plus the request that started it, kept for audit and review.

    Only the store and the workflow see this; the API returns `RunRecord`, so
    a feature's worker prompt and schema are not echoed back to every poll.
    """

    request: RunRequest


class RunSummary(StrictModel):
    run_id: str
    feature: str
    task: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    verdict: Verdict | None = None
    decision: Decision | None = None


class HistoryEvent(StrictModel):
    sequence: int
    run_id: str
    at: datetime
    actor: str
    event: str
    detail: dict[str, Any] = Field(default_factory=dict)


class DependencyStatus(StrictModel):
    status: str
    service: str
    detail: str
    code: str | None = None


class HealthResponse(StrictModel):
    status: str
    service: str
    dependencies: dict[str, DependencyStatus]
    active_runs: int
