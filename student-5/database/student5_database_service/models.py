from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

T = TypeVar("T")

TripIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=100)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
RequiredText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
OptionalText = Annotated[str, StringConstraints(max_length=2000)]
Money = Annotated[
    Decimal,
    Field(ge=Decimal("0.00"), le=Decimal("1000000000.00"), decimal_places=2),
]
PositiveMoney = Annotated[
    Decimal,
    Field(gt=Decimal("0.00"), le=Decimal("1000000000.00"), decimal_places=2),
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


class DeleteResponse(StrictModel):
    id: UUID
    deleted: bool = True


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
        allocated = sum(
            (
                self.accommodation_budget,
                self.transport_budget,
                self.activities_budget,
                self.food_budget,
                self.other_budget,
            ),
            Decimal("0.00"),
        )
        if allocated > self.total_budget:
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

    @field_validator("payment_method", "notes")
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


class ExpenseRecord(ExpenseFields):
    expense_id: UUID
    created_at: datetime
    updated_at: datetime
