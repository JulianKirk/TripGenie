from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

TripIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
RequiredText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
OptionalText = Annotated[str, StringConstraints(max_length=2000)]
AnalysisQuestion = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Money = Annotated[
    Decimal,
    Field(ge=Decimal("0.00"), le=Decimal("1000000000.00"), decimal_places=2),
]
PositiveMoney = Annotated[
    Decimal,
    Field(gt=Decimal("0.00"), le=Decimal("1000000000.00"), decimal_places=2),
]
SignedMoney = Annotated[
    Decimal,
    Field(ge=Decimal("-1000000000.00"), le=Decimal("1000000000.00"), decimal_places=2),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpenseCategory(str, Enum):
    ACCOMMODATION = "accommodation"
    TRANSPORT = "transport"
    ACTIVITIES = "activities"
    FOOD = "food"
    SHOPPING = "shopping"
    OTHER = "other"


class BudgetFields(StrictModel):
    trip_id: TripIdentifier
    currency: CurrencyCode
    total_budget: Money
    accommodation_budget: Money = Decimal("0.00")
    transport_budget: Money = Decimal("0.00")
    activities_budget: Money = Decimal("0.00")
    food_budget: Money = Decimal("0.00")
    other_budget: Money = Decimal("0.00")

    @model_validator(mode="after")
    def allocations_must_fit_total(self) -> BudgetFields:
        allocations = (
            self.accommodation_budget,
            self.transport_budget,
            self.activities_budget,
            self.food_budget,
            self.other_budget,
        )
        if sum(allocations, Decimal("0.00")) > self.total_budget:
            raise ValueError("category allocations must not exceed total_budget")
        return self


class BudgetCreate(BudgetFields):
    budget_id: UUID | None = None


class BudgetUpdate(StrictModel):
    trip_id: TripIdentifier | None = None
    currency: CurrencyCode | None = None
    total_budget: Money | None = None
    accommodation_budget: Money | None = None
    transport_budget: Money | None = None
    activities_budget: Money | None = None
    food_budget: Money | None = None
    other_budget: Money | None = None


class BudgetRecord(BudgetFields):
    budget_id: UUID
    created_at: datetime
    updated_at: datetime


class ExpenseFields(StrictModel):
    trip_id: TripIdentifier
    category: ExpenseCategory
    description: RequiredText
    amount: PositiveMoney
    currency: CurrencyCode
    date: Date
    payment_method: RequiredText | None = None
    notes: OptionalText | None = None

    @field_validator("payment_method", "notes", mode="before")
    @classmethod
    def blank_optional_text_becomes_none(cls, value: str | None) -> str | None:
        return value or None


class ExpenseCreate(ExpenseFields):
    expense_id: UUID | None = None


class ExpenseUpdate(StrictModel):
    trip_id: TripIdentifier | None = None
    category: ExpenseCategory | None = None
    description: RequiredText | None = None
    amount: PositiveMoney | None = None
    currency: CurrencyCode | None = None
    date: Date | None = None
    payment_method: RequiredText | None = None
    notes: OptionalText | None = None

    @field_validator("payment_method", "notes", mode="before")
    @classmethod
    def blank_optional_text_becomes_none(cls, value: str | None) -> str | None:
        return value or None


class ExpenseRecord(ExpenseFields):
    expense_id: UUID
    created_at: datetime
    updated_at: datetime


class TripRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: TripIdentifier
    name: RequiredText | None = None
    destination: RequiredText | None = None
    start_date: Date
    end_date: Date
    status: RequiredText | None = None


class ProviderStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"


class ProviderCostItem(StrictModel):
    item_id: str
    description: str
    status: str
    amount: Money
    currency: CurrencyCode

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"


class ProviderCost(StrictModel):
    provider: str
    status: ProviderStatus
    subtotal: Money | None = None
    currency: CurrencyCode | None = None
    detail: str | None = None
    items: list[ProviderCostItem] = Field(default_factory=list)

    @field_serializer("subtotal")
    def serialize_subtotal(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.2f}"


class BudgetSummary(StrictModel):
    budget_id: UUID
    trip_id: TripIdentifier
    currency: CurrencyCode
    total_budget: Money
    actual_spending: Money
    actual_spending_complete: bool
    unconverted_expense_count: int = Field(ge=0)
    committed_costs: Money
    committed_costs_complete: bool
    remaining_budget: SignedMoney
    remaining_budget_complete: bool
    category_totals: dict[ExpenseCategory, Money]
    providers: dict[str, ProviderCost]


class BudgetAnalysisRequest(StrictModel):
    question: AnalysisQuestion


class BudgetAnalysis(StrictModel):
    overview: Annotated[
        str,
        StringConstraints(min_length=1, max_length=400),
        Field(
            description=(
                "A concise direct answer quoting at least one exact supplied currency "
                "amount and accurately stating relevant uncertainty."
            )
        ),
    ]
    risks: list[
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=180),
            Field(description="One distinct risk supported by the supplied context."),
        ]
    ] = Field(max_length=3)
    recommendations: list[
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=180),
            Field(description="One concise, practical, non-contradictory next step."),
        ]
    ] = Field(min_length=1, max_length=3)
    disclaimer: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class BudgetAnalysisResponse(StrictModel):
    analysis: BudgetAnalysis
    run_id: str
    model: str
    provider: str


class RagQueryRequest(StrictModel):
    question: AnalysisQuestion


class UpstreamModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RagCitation(UpstreamModel):
    source_id: str
    title: str
    section: str
    path: str
    chunk_id: str
    excerpt: str


class RagRetrieval(UpstreamModel):
    requested_top_k: int
    returned_chunks: int
    maximum_score: float | None


class RagAnswer(UpstreamModel):
    answer: str
    confidence_category: Literal["high", "medium", "low", "insufficient_context"]
    insufficient_context: bool
    citations: list[RagCitation]
    retrieval: RagRetrieval
    run_id: str
    correlation_id: str

    @model_validator(mode="after")
    def grounding_is_consistent(self) -> RagAnswer:
        if self.insufficient_context:
            if self.citations or self.confidence_category != "insufficient_context":
                raise ValueError("insufficient context must have no citations")
        elif not self.citations or self.confidence_category == "insufficient_context":
            raise ValueError("a grounded answer needs citations and a confidence")
        return self


class ToolTrace(UpstreamModel):
    tool: str
    arguments: dict[str, Any]
    status: Literal["success", "error", "rejected"]
    duration_ms: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None


class McpActionResult(StrictModel):
    action: str
    correlation_id: str
    duration_ms: int
    run_id: str
    model: str
    provider: str
    answer: str
    tools: list[ToolTrace]


AgentRunId = Annotated[str, StringConstraints(pattern=r"^magent_[0-9a-f]{12}$")]
AllocationCategory = Literal[
    "accommodation", "transport", "activities", "food", "other"
]
AgentText = Annotated[str, StringConstraints(min_length=1, max_length=240)]


class BudgetAgentAction(StrictModel):
    category: AllocationCategory
    new_allocation: Annotated[
        str,
        StringConstraints(pattern=r"^\d{1,10}\.\d{2}$"),
        Field(description="Proposed category allocation, e.g. 450.00."),
    ]
    reason: AgentText


class BudgetAgentDraft(StrictModel):
    budget_id: Annotated[
        str, Field(description="The budget_id returned by budgets_get_summary.")
    ]
    overview: Annotated[
        str,
        StringConstraints(min_length=1, max_length=600),
        Field(description="Direct answer quoting exact amounts from tool results."),
    ]
    findings: list[AgentText] = Field(max_length=4)
    actions: list[BudgetAgentAction] = Field(
        max_length=3,
        description="Allocation changes for a human to approve; may be empty.",
    )


class AgentRunRequest(StrictModel):
    question: AnalysisQuestion


AllocationAmount = Annotated[str, StringConstraints(pattern=r"^\d{1,10}\.\d{2}$")]


class AgentReviewRequest(StrictModel):
    decision: Literal["approve", "correct", "reject"]
    reviewer: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    notes: Annotated[str, StringConstraints(max_length=1000)] | None = None
    accepted: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    corrected_allocations: dict[Annotated[int, Field(ge=0)], AllocationAmount] = Field(
        default_factory=dict
    )
    corrected_overview: (
        Annotated[str, StringConstraints(min_length=1, max_length=600)] | None
    ) = None

    @field_validator("notes", "corrected_overview", mode="before")
    @classmethod
    def blank_text_becomes_none(cls, value: str | None) -> str | None:
        return value.strip() or None if isinstance(value, str) else value


class AgentPlan(StrictModel):
    goal: str
    steps: list[str]


class AgentStage(StrictModel):
    agent: str
    attempt: int
    status: str
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None
    tools: list[ToolTrace] = Field(default_factory=list)


class AgentCheck(StrictModel):
    name: str
    passed: bool
    detail: str


class AgentReview(StrictModel):
    verdict: str
    summary: str
    issues: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AgentHumanDecision(StrictModel):
    decision: str
    reviewer: str
    notes: str | None = None
    decided_at: str


class AgentProposedAction(StrictModel):
    index: int
    category: AllocationCategory
    current_allocation: str | None
    new_allocation: str
    reason: str


class AgentAppliedChange(StrictModel):
    category: AllocationCategory
    previous: str
    new: str


class AgentHistoryEvent(StrictModel):
    sequence: int
    at: str
    actor: str
    event: str


class AgentRunView(StrictModel):
    run_id: str
    status: str
    active: bool
    task: str
    attempts: int
    created_at: str
    updated_at: str
    plan: AgentPlan | None = None
    stages: list[AgentStage] = Field(default_factory=list)
    checks: list[AgentCheck] = Field(default_factory=list)
    review: AgentReview | None = None
    budget_id: str | None = None
    grounded: bool = False
    overview: str | None = None
    findings: list[str] = Field(default_factory=list)
    actions: list[AgentProposedAction] = Field(default_factory=list)
    human: AgentHumanDecision | None = None
    error: dict[str, str] | None = None
    history: list[AgentHistoryEvent] = Field(default_factory=list)
    applied_changes: list[AgentAppliedChange] = Field(default_factory=list)
    apply_error: str | None = None
