"""Read models for the responses the Student 3 backend returns.

The frontend posts plain form data and lets the backend validate it, so there
are no write models here. These exist so a malformed backend response is caught
at the boundary instead of blowing up inside a template.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class LenientModel(BaseModel):
    """Ignores unknown fields so a backend addition cannot break rendering."""

    model_config = ConfigDict(extra="ignore")


class TransportType(str, Enum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"
    FERRY = "ferry"
    CAR_RENTAL = "car_rental"
    TRANSFER = "transfer"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    LIMITED = "limited"
    SOLD_OUT = "sold_out"
    CANCELLED = "cancelled"


class PlanStatus(str, Enum):
    """Plan states. TripGenie does not place reservations with carriers."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


PLAN_STATUS_LABELS = {
    PlanStatus.PENDING: "Shortlisted",
    PlanStatus.CONFIRMED: "In the itinerary",
    PlanStatus.CANCELLED: "Removed",
    PlanStatus.COMPLETED: "Journey taken",
}

ACTIVE_PLAN_STATUSES = frozenset(
    {PlanStatus.PENDING, PlanStatus.CONFIRMED, PlanStatus.COMPLETED},
)


class DataEnvelope(LenientModel, Generic[T]):
    data: T


class ErrorDetail(LenientModel):
    field: str
    issue: str


class ErrorBody(LenientModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(LenientModel):
    error: ErrorBody


class DeleteResponse(LenientModel):
    id: str
    deleted: bool = True


class DependencyStatus(LenientModel):
    status: str
    service: str
    detail: str
    code: str | None = None


class BackendHealthPayload(LenientModel):
    status: str
    service: str
    dependencies: dict[str, DependencyStatus] = Field(default_factory=dict)


class FrontendHealthDependencies(LenientModel):
    backend: DependencyStatus


class HealthResponse(LenientModel):
    status: str
    service: str
    dependencies: FrontendHealthDependencies


class TransportOptionRecord(LenientModel):
    id: str
    type: TransportType
    provider: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    departure_utc_offset: int | None = None
    arrival_utc_offset: int | None = None
    duration_minutes: int
    price: float
    capacity: int
    availability_status: AvailabilityStatus
    seats_remaining: int
    notes: str | None = None

    @property
    def duration_label(self) -> str:
        hours, minutes = divmod(self.duration_minutes, 60)
        if hours and minutes:
            return f"{hours}h {minutes}m"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"

    @property
    def crosses_time_zones(self) -> bool:
        return (
            self.departure_utc_offset is not None
            and self.arrival_utc_offset is not None
            and self.departure_utc_offset != self.arrival_utc_offset
        )

    @property
    def type_label(self) -> str:
        return self.type.value.replace("_", " ").title()

    @property
    def availability_label(self) -> str:
        return self.availability_status.value.replace("_", " ").title()


class TransportPlanEntryRecord(LenientModel):
    id: str
    trip_id: str
    transport_id: str
    traveller_count: int
    booking_date: str
    estimated_cost: float
    booking_status: PlanStatus
    notes: str | None = None

    @property
    def status_label(self) -> str:
        return PLAN_STATUS_LABELS[self.booking_status]

    @property
    def is_active(self) -> bool:
        return self.booking_status in ACTIVE_PLAN_STATUSES


class TripSummary(LenientModel):
    id: str
    name: str
    destination: str
    start_date: str
    end_date: str
    status: str | None = None

    @property
    def label(self) -> str:
        """What a traveller reads in the picker, instead of a raw identifier."""
        return f"{self.name} — {self.destination}, {self.start_date} to {self.end_date}"


class TripDirectory(LenientModel):
    available: bool
    trips: list[TripSummary] = Field(default_factory=list)


class PlannedTransport(LenientModel):
    entry: TransportPlanEntryRecord
    option: TransportOptionRecord


class TripTransportSummary(LenientModel):
    trip_id: str
    entry_count: int
    active_entry_count: int
    estimated_cost_total: float
    planned: list[PlannedTransport]
