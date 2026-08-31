"""Student 1's itinerary service, as this service sees it.

The accommodation frontend must reach exactly one backend -- this one -- so the
call to another student's service is made here rather than there. This module is
the only place that knows student 1 speaks HTTP, wraps its responses in a
`{"data": ...}` envelope, and calls a trip what we call an itinerary.

Failures map through the same `client.request` the database service uses, so a
student 1 outage is the documented 503 and a malformed answer is a 502.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from backend_service.client import request

if TYPE_CHECKING:
    from uuid import UUID

    from backend_service.config import Settings

UNAVAILABLE = "itinerary service unavailable"


class ItineraryClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        self._prefix = settings.itinerary_prefix
        # `transport` is the same test seam the database client uses.
        self._client = httpx.AsyncClient(
            base_url=settings.itinerary_url,
            timeout=settings.itinerary_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_itineraries(self) -> list[dict[str, Any]]:
        return await self._data("GET", "/trips")

    async def itineraries_with(self, accommodation_id: UUID) -> list[dict[str, Any]]:
        """The reverse lookup: every itinerary already holding this
        accommodation. One call, so the picker does not ask per itinerary."""
        return await self._data("GET", f"/accommodations/{accommodation_id}/trips")

    async def add(self, accommodation_id: UUID, itinerary_id: str) -> dict[str, Any]:
        return await self._data(
            "PUT", f"/trips/{itinerary_id}/accommodations/{accommodation_id}"
        )

    async def remove(self, accommodation_id: UUID, itinerary_id: str) -> dict[str, Any]:
        return await self._data(
            "DELETE", f"/trips/{itinerary_id}/accommodations/{accommodation_id}"
        )

    async def _data(self, method: str, path: str, **kwargs: Any) -> Any:
        """Student 1 envelopes every success body. Unwrapping in one place keeps
        `{"data": ...}` out of the routers."""
        body = await request(
            self._client,
            method,
            f"{self._prefix}{path}",
            unavailable=UNAVAILABLE,
            **kwargs,
        )
        return body["data"] if isinstance(body, dict) and "data" in body else body
