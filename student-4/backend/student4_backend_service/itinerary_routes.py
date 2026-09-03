from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from .dependencies import DbDep, ItineraryDep  # noqa: TC001 (FastAPI runtime)
from .schemas import (
    ActivityCostItem,
    ActivityCostResponse,
    ActivitySchedule,
    ItinerarySelection,
    ItinerarySelectionResponse,
    TripActivityWire,
)

router = APIRouter(prefix="/activity", tags=["itinerary"])


@router.get(
    "/trips/{itinerary_id}/committed-costs",
    response_model=ActivityCostResponse,
)
async def committed_costs(
    itinerary_id: str, itinerary: ItineraryDep, db: DbDep
) -> ActivityCostResponse:
    trips, rows = await asyncio.gather(
        itinerary.list_itineraries(), itinerary.activities_in(itinerary_id)
    )
    trip = next((record for record in trips if record.id == itinerary_id), None)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "itinerary not found")

    activities = await asyncio.gather(*(db.get(UUID(row.activity_id)) for row in rows))
    items = [
        ActivityCostItem(
            item_id=activity.id,
            description=activity.name,
            amount=f"{activity.price * trip.traveller_count:.2f}"
            if activity.pricing_basis == "PER_PERSON"
            else f"{activity.price:.2f}",
        )
        for activity in activities
    ]
    total = sum((item.amount for item in items), Decimal("0.00"))
    return ActivityCostResponse(
        committed_cost_total=f"{total:.2f}",
        items=items,
    )


async def selection(
    activity_id: UUID, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    all_trips, holding_trips = await asyncio.gather(
        itinerary.list_itineraries(), itinerary.with_activity(activity_id)
    )
    holding = {trip.id for trip in holding_trips}
    selected_ids = sorted(holding)
    rows = await asyncio.gather(
        *(itinerary.activities_in(trip_id) for trip_id in selected_ids)
    )
    schedules: dict[str, TripActivityWire | None] = {}
    for trip_id, trip_rows in zip(selected_ids, rows, strict=True):
        schedules[trip_id] = next(
            (row for row in trip_rows if row.activity_id == str(activity_id)), None
        )
    selections: list[ItinerarySelection] = []
    for trip in all_trips:
        schedule = schedules.get(trip.id)
        selections.append(
            ItinerarySelection(
                itinerary_id=trip.id,
                name=trip.name,
                selected=trip.id in holding,
                start_date=trip.start_date,
                end_date=trip.end_date,
                date=schedule.date if schedule else None,
                start_time=schedule.start_time if schedule else None,
            )
        )
    return ItinerarySelectionResponse(itineraries=selections)


@router.get("/{activity_id}/itineraries", response_model=ItinerarySelectionResponse)
async def list_itineraries(
    activity_id: UUID, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    return await selection(activity_id, itinerary)


@router.put(
    "/{activity_id}/itineraries/{itinerary_id}",
    response_model=ItinerarySelectionResponse,
)
async def add_to_itinerary(
    activity_id: UUID,
    itinerary_id: str,
    itinerary: ItineraryDep,
    schedule: ActivitySchedule | None = None,
) -> ItinerarySelectionResponse:
    await itinerary.add(
        activity_id,
        itinerary_id,
        schedule.date.isoformat() if schedule and schedule.date else None,
        schedule.start_time.strftime("%H:%M")
        if schedule and schedule.start_time
        else None,
    )
    return await selection(activity_id, itinerary)


@router.delete(
    "/{activity_id}/itineraries/{itinerary_id}",
    response_model=ItinerarySelectionResponse,
)
async def remove_from_itinerary(
    activity_id: UUID, itinerary_id: str, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    await itinerary.remove(activity_id, itinerary_id)
    return await selection(activity_id, itinerary)
