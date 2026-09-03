"""Adding an accommodation to one of student 1's itineraries.

The accommodation frontend talks to this service and nothing else, so the call
across to student 1 is made here. Every route answers with the *whole* picker
state rather than just the row that changed, so one response repaints the
trip card and a tick can never disagree with what student 1 stored.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from backend_service.dependencies import DbDep, ItineraryDep  # noqa: TC001  (runtime)
from backend_service.schemas import (
    AccommodationCostItem,
    AccommodationCostResponse,
    ItinerarySelection,
    ItinerarySelectionResponse,
    StayDates,
)

if TYPE_CHECKING:
    from backend_service.itinerary_client import ItineraryClient

router = APIRouter(prefix="/accommodation", tags=["itinerary"])


@router.get(
    "/trips/{itinerary_id}/committed-costs",
    response_model=AccommodationCostResponse,
)
async def committed_costs(
    itinerary_id: str, itinerary: ItineraryDep, db: DbDep
) -> AccommodationCostResponse:
    items: list[AccommodationCostItem] = []
    try:
        for stay in await itinerary.stays_in(itinerary_id):
            check_in = date.fromisoformat(stay["date"])
            check_out = date.fromisoformat(stay["check_out"])
            accommodation = await db.get(UUID(stay["accommodation_id"]))
            rate = Decimal(str(accommodation["price_per_night"]))
            amount = rate * (check_out - check_in).days
            items.append(
                AccommodationCostItem(
                    item_id=accommodation["id"],
                    description=accommodation["name"],
                    amount=amount,
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "incomplete accommodation stay cost data",
        ) from exc
    return AccommodationCostResponse(
        committed_cost_total=sum((item.amount for item in items), Decimal("0.00")),
        items=items,
    )


async def _selection(
    itinerary: ItineraryClient, accommodation_id: UUID
) -> ItinerarySelectionResponse:
    """Every itinerary, ticked where this accommodation already sits on it,
    and the stay dates on the ticked ones.

    Two calls for the ticks -- the full list gives the unticked ones and the
    reverse lookup gives the ticked ones -- and then one per ticked itinerary
    for its dates, because the reverse lookup returns trips rather than the
    rows pinning them.
    """
    everything = await itinerary.list_itineraries()
    holding = {
        record["id"] for record in await itinerary.itineraries_with(accommodation_id)
    }
    stays = await _stays(itinerary, accommodation_id, holding)
    return ItinerarySelectionResponse(
        itineraries=[
            ItinerarySelection(
                itinerary_id=record["id"],
                name=record["name"],
                selected=record["id"] in holding,
                start_date=record["start_date"],
                end_date=record["end_date"],
                check_in=stays.get(record["id"], {}).get("date"),
                check_in_time=stays.get(record["id"], {}).get("check_in_time"),
                check_out=stays.get(record["id"], {}).get("check_out"),
                check_out_time=stays.get(record["id"], {}).get("check_out_time"),
            )
            for record in everything
        ]
    )


async def _stays(
    itinerary: ItineraryClient,
    accommodation_id: UUID,
    holding: set[str],
) -> dict[str, dict[str, Any]]:
    """The stored stay per itinerary already holding this accommodation.

    ponytail: one call per *ticked* itinerary, gathered. N is the itineraries
    holding this one accommodation -- normally none or a handful, not the
    length of the itinerary list -- so the picker stays one round trip deep.
    If that stops being true, the fix is for student 1's reverse lookup to
    carry the dates, not a cache here.
    """
    if not holding:
        return {}

    ordered = sorted(holding)
    results = await asyncio.gather(
        *(itinerary.stays_in(itinerary_id) for itinerary_id in ordered),
        return_exceptions=True,
    )

    stays: dict[str, dict[str, Any]] = {}
    for itinerary_id, result in zip(ordered, results, strict=True):
        # A tick is the picker's job; the dates are a bonus. One failing
        # lookup must not blank a list that is otherwise correct.
        if isinstance(result, BaseException):
            continue
        for row in result:
            if str(row.get("accommodation_id")) == str(accommodation_id):
                stays[itinerary_id] = row
                break
    return stays


@router.get("/{id:uuid}/itineraries", response_model=ItinerarySelectionResponse)
async def list_itineraries(
    id: UUID, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    return await _selection(itinerary, id)


@router.put(
    "/{id:uuid}/itineraries/{itinerary_id}", response_model=ItinerarySelectionResponse
)
async def add_to_itinerary(
    id: UUID,
    itinerary_id: str,
    itinerary: ItineraryDep,
    stay: StayDates | None = None,
) -> ItinerarySelectionResponse:
    """The body is optional so a caller that only wants the pin, and does not
    care when, keeps working -- student 1 falls back to the trip's first day."""
    await itinerary.add(
        id,
        itinerary_id,
        stay.check_in if stay else None,
        stay.check_out if stay else None,
        stay.check_in_time if stay else None,
        stay.check_out_time if stay else None,
    )
    return await _selection(itinerary, id)


@router.delete(
    "/{id:uuid}/itineraries/{itinerary_id}", response_model=ItinerarySelectionResponse
)
async def remove_from_itinerary(
    id: UUID, itinerary_id: str, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    await itinerary.remove(id, itinerary_id)
    return await _selection(itinerary, id)
