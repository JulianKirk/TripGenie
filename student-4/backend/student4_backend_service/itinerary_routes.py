from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID  # noqa: TC003 (FastAPI reads this at runtime)

from fastapi import APIRouter

from .dependencies import ItineraryDep  # noqa: TC001 (FastAPI runtime)
from .schemas import (
    ActivitySchedule,
    ItinerarySelection,
    ItinerarySelectionResponse,
)

router = APIRouter(prefix="/activity", tags=["itinerary"])


async def selection(
    activity_id: UUID, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    all_trips, holding_trips = await asyncio.gather(
        itinerary.list(), itinerary.with_activity(activity_id)
    )
    holding = {trip["id"] for trip in holding_trips}
    selected_ids = sorted(holding)
    rows = await asyncio.gather(
        *(itinerary.activities_in(trip_id) for trip_id in selected_ids)
    )
    schedules: dict[str, dict[str, Any]] = {}
    for trip_id, trip_rows in zip(selected_ids, rows, strict=True):
        schedules[trip_id] = next(
            (
                row
                for row in trip_rows
                if str(row.get("activity_id")) == str(activity_id)
            ),
            {},
        )
    return ItinerarySelectionResponse(
        itineraries=[
            ItinerarySelection(
                itinerary_id=trip["id"],
                name=trip["name"],
                selected=trip["id"] in holding,
                start_date=trip["start_date"],
                end_date=trip["end_date"],
                date=schedules.get(trip["id"], {}).get("date"),
                start_time=schedules.get(trip["id"], {}).get("start_time"),
            )
            for trip in all_trips
        ]
    )


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
