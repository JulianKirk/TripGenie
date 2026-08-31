"""Adding an accommodation to one of student 1's itineraries.

The accommodation frontend talks to this service and nothing else, so the call
across to student 1 is made here. Every route answers with the *whole* picker
state rather than just the row that changed, so one response repaints the
dropdown and a tick can never disagree with what student 1 stored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter

from backend_service.dependencies import ItineraryDep  # noqa: TC001  (runtime)
from backend_service.schemas import ItinerarySelection, ItinerarySelectionResponse

if TYPE_CHECKING:
    from backend_service.itinerary_client import ItineraryClient

router = APIRouter(prefix="/accommodation", tags=["itinerary"])


async def _selection(
    itinerary: ItineraryClient, accommodation_id: UUID
) -> ItinerarySelectionResponse:
    """Every itinerary, ticked where this accommodation already sits on it.

    Two calls, not one per itinerary: the full list gives the unticked ones and
    the reverse lookup gives the ticked ones.
    """
    everything = await itinerary.list_itineraries()
    holding = {
        record["id"] for record in await itinerary.itineraries_with(accommodation_id)
    }
    return ItinerarySelectionResponse(
        itineraries=[
            ItinerarySelection(
                itinerary_id=record["id"],
                name=record["name"],
                selected=record["id"] in holding,
            )
            for record in everything
        ]
    )


@router.get("/{id:uuid}/itineraries", response_model=ItinerarySelectionResponse)
async def list_itineraries(
    id: UUID, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    return await _selection(itinerary, id)


@router.put(
    "/{id:uuid}/itineraries/{itinerary_id}", response_model=ItinerarySelectionResponse
)
async def add_to_itinerary(
    id: UUID, itinerary_id: str, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    await itinerary.add(id, itinerary_id)
    return await _selection(itinerary, id)


@router.delete(
    "/{id:uuid}/itineraries/{itinerary_id}", response_model=ItinerarySelectionResponse
)
async def remove_from_itinerary(
    id: UUID, itinerary_id: str, itinerary: ItineraryDep
) -> ItinerarySelectionResponse:
    await itinerary.remove(id, itinerary_id)
    return await _selection(itinerary, id)
