"""Accommodation booking endpoints."""

from __future__ import annotations

from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, status

from database_service.dependencies import (
    LimitDep,
    OffsetDep,
    SessionDep,
    get_or_404,
)
from database_service.models import AccommodationBooking
from database_service.repository import (
    AccommodationBookingRepository,
    AccommodationRepository,
)
from database_service.schemas import (
    BookingCreate,
    BookingCreated,
    BookingList,
    BookingOut,
)

router = APIRouter(prefix="/accommodation/booking", tags=["booking"])


@router.get("", response_model=BookingList)
def list_bookings(
    session: SessionDep, limit: LimitDep = 20, offset: OffsetDep = 0
) -> BookingList:
    rows, total = AccommodationBookingRepository(session).list(limit, offset)
    return BookingList(bookings=rows, total=total)


@router.get("/{id:uuid}", response_model=BookingOut)
def get_booking(id: UUID, session: SessionDep) -> AccommodationBooking:
    return get_or_404(AccommodationBookingRepository(session), id, "booking")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=BookingCreated)
def create_booking(payload: BookingCreate, session: SessionDep) -> AccommodationBooking:
    get_or_404(
        AccommodationRepository(session), payload.accommodation_id, "accommodation"
    )
    return AccommodationBookingRepository(session).add(
        AccommodationBooking(**payload.model_dump())
    )


@router.delete("/{id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(id: UUID, session: SessionDep) -> None:
    bookings = AccommodationBookingRepository(session)
    get_or_404(bookings, id, "booking")
    bookings.delete(id)
