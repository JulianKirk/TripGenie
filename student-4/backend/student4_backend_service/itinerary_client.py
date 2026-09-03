from __future__ import annotations

from typing import Any
from uuid import UUID  # noqa: TC003 (runtime client API)

import httpx

from .client import parse, request
from .config import Settings  # noqa: TC001 (runtime constructor contract)
from .schemas import (
    DataEnvelope,
    ItineraryTrip,
    StudentDeleteResponse,
    StudentErrorEnvelope,
    TripActivityWire,
)


def _error_detail(body: Any) -> str:
    envelope = parse(StudentErrorEnvelope, body, "bad response from itinerary service")
    return envelope.error.message


class ItineraryClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._prefix = settings.itinerary_prefix
        self._client = httpx.AsyncClient(
            base_url=settings.itinerary_url,
            timeout=settings.itinerary_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_itineraries(self) -> list[ItineraryTrip]:
        body = await self._request("GET", "/trips")
        return parse(
            DataEnvelope[list[ItineraryTrip]],
            body,
            "bad response from itinerary service",
        ).data

    async def with_activity(self, activity_id: UUID) -> list[ItineraryTrip]:
        body = await self._request("GET", f"/activities/{activity_id}/trips")
        return parse(
            DataEnvelope[list[ItineraryTrip]],
            body,
            "bad response from itinerary service",
        ).data

    async def activities_in(self, itinerary_id: str) -> list[TripActivityWire]:
        body = await self._request("GET", f"/trips/{itinerary_id}/activities")
        return parse(
            DataEnvelope[list[TripActivityWire]],
            body,
            "bad response from itinerary service",
        ).data

    async def add(
        self,
        activity_id: UUID,
        itinerary_id: str,
        date: str | None,
        start_time: str | None,
    ) -> TripActivityWire:
        body = {
            key: value
            for key, value in {"date": date, "start_time": start_time}.items()
            if value is not None
        }
        response = await self._request(
            "PUT", f"/trips/{itinerary_id}/activities/{activity_id}", json=body
        )
        return parse(
            DataEnvelope[TripActivityWire],
            response,
            "bad response from itinerary service",
        ).data

    async def remove(
        self, activity_id: UUID, itinerary_id: str
    ) -> StudentDeleteResponse:
        response = await self._request(
            "DELETE", f"/trips/{itinerary_id}/activities/{activity_id}"
        )
        return parse(
            DataEnvelope[StudentDeleteResponse],
            response,
            "bad response from itinerary service",
        ).data

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await request(
            self._client,
            method,
            f"{self._prefix}{path}",
            unavailable="itinerary service unavailable",
            bad_response="bad response from itinerary service",
            client_error_detail=_error_detail,
            **kwargs,
        )
