"""Messages for the Release 2 multi-agent routes.

Two groups: the *draft* the Worker must answer with (its JSON Schema goes to the
server as the run's output schema), and the *view* this service shows a person
for a run. The server owns the run record; the view is that record narrowed to
what this feature displays, with each suggested id re-read from the database.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from backend_service.schemas import Accommodation

MAX_SUGGESTIONS = 5
UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

AgentRunIdentifier = Annotated[str, StringConstraints(pattern=r"^magent_[0-9a-f]{12}$")]
AgentRunStatus = Literal[
    "planning",
    "working",
    "reviewing",
    "awaiting_human",
    "completed",
    "rejected",
    "failed",
]
HumanDecision = Literal["approve", "correct", "partial", "reject"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------- the draft


class SuggestionDraft(Strict):
    accommodation_id: Annotated[str, StringConstraints(pattern=UUID_PATTERN)]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class AccommodationRecommendationDraft(Strict):
    """What the Worker answers with. Ids only: the rows are read back from the
    database, so a made-up price or name can never reach a person."""

    overview: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    suggestions: list[SuggestionDraft] = Field(
        default_factory=list, max_length=MAX_SUGGESTIONS
    )
    considerations: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=MAX_SUGGESTIONS
    )


# ---------------------------------------------------------------- requests


class AgentRunRequest(Strict):
    """An accommodation question for the shared Planner -> Worker -> Reviewer
    run. A human decides what, if anything, is added to the trip."""

    question: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    trip_id: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = (
        None
    )
    country: Annotated[str, StringConstraints(max_length=100)] | None = None
    city: Annotated[str, StringConstraints(max_length=100)] | None = None

    @field_validator("trip_id", "country", "city")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class AgentReviewRequest(Strict):
    """The human decision on a run awaiting review.

    `accepted` indexes the run's suggestions: the ones to keep for `partial`,
    and the corrected answer's suggestions for `correct`. Accepted suggestions
    are pinned to the run's trip by this service's own itinerary route, for the
    given stay dates (student 1 defaults them to the trip's first day).
    """

    decision: HumanDecision
    reviewer: Annotated[str, StringConstraints(min_length=1, max_length=60)] = (
        "traveller"
    )
    notes: Annotated[str, StringConstraints(max_length=1000)] | None = None
    accepted: list[Annotated[int, Field(ge=0)]] = Field(
        default_factory=list, max_length=MAX_SUGGESTIONS
    )
    corrected_overview: (
        Annotated[str, StringConstraints(min_length=1, max_length=400)] | None
    ) = None
    check_in: str | None = None
    check_out: str | None = None

    @field_validator("notes", "corrected_overview", "check_in", "check_out")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return value or None


# ---------------------------------------------------------------- the view


class AgentPlan(Strict):
    goal: str
    steps: list[str]


class AgentToolCall(Strict):
    """One MCP tool call the Worker made. `accommodation_ids` are the listings
    that call returned; only those can back a suggestion."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error", "rejected"]
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None
    accommodation_ids: list[str] = Field(default_factory=list)


class AgentStage(Strict):
    agent: Literal["planner", "worker", "reviewer"]
    attempt: int = Field(ge=1)
    status: str
    duration_ms: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None
    tools: list[AgentToolCall] = Field(default_factory=list)


class AgentCheck(Strict):
    """A deterministic check the Multi-Agent Server ran on the Worker's answer."""

    name: str
    passed: bool
    detail: str


class AgentReview(Strict):
    verdict: Literal["approve", "revise", "reject"]
    summary: str
    issues: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AgentSuggestion(Strict):
    """A suggested listing, re-read from the database.

    `grounded` is true only when a successful accommodation tool in the Worker's
    final attempt returned the id; only those can be added to a trip.
    `accommodation` is None when the listing no longer exists.
    """

    index: int = Field(ge=0)
    accommodation_id: str
    reason: str
    grounded: bool
    accommodation: Accommodation | None = None


class AgentHumanDecision(Strict):
    decision: HumanDecision
    reviewer: str
    notes: str | None = None
    decided_at: str


class AgentSavedStay(Strict):
    accommodation_id: str
    trip_id: str
    check_in: str | None = None
    check_out: str | None = None


class AgentSaveError(Strict):
    accommodation_id: str
    code: str
    message: str


class AgentRunError(Strict):
    code: str
    message: str


class AgentRunView(Strict):
    """A multi-agent run as this feature shows it. `saved` and `save_errors`
    are filled only in the reply to a decision."""

    run_id: AgentRunIdentifier
    status: AgentRunStatus
    task: str
    trip_id: str | None = None
    attempts: int = Field(ge=0)
    created_at: str
    updated_at: str
    plan: AgentPlan | None = None
    stages: list[AgentStage] = Field(default_factory=list)
    checks: list[AgentCheck] = Field(default_factory=list)
    review: AgentReview | None = None
    overview: str | None = None
    considerations: list[str] = Field(default_factory=list)
    suggestions: list[AgentSuggestion] = Field(default_factory=list)
    human: AgentHumanDecision | None = None
    error: AgentRunError | None = None
    saved: list[AgentSavedStay] = Field(default_factory=list)
    save_errors: list[AgentSaveError] = Field(default_factory=list)
