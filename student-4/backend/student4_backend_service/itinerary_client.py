from __future__ import annotations

from typing import Any
from uuid import UUID  # noqa: TC003 (runtime client API)

import httpx

from .client import request
from .config import Settings  # noqa: TC001 (runtime constructor contract)


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

    async def list(self) -> list[dict[str, Any]]:
        return await self._data("GET", "/trips")

    async def with_activity(self, activity_id: UUID) -> list[dict[str, Any]]:
        return await self._data("GET", f"/activities/{activity_id}/trips")

    async def activities_in(self, itinerary_id: str) -> list[dict[str, Any]]:
        return await self._data("GET", f"/trips/{itinerary_id}/activities")

    async def add(
        self,
        activity_id: UUID,
        itinerary_id: str,
        date: str | None,
        start_time: str | None,
    ) -> dict[str, Any]:
        body = {
            key: value
            for key, value in {"date": date, "start_time": start_time}.items()
            if value is not None
        }
        return await self._data(
            "PUT",
            f"/trips/{itinerary_id}/activities/{activity_id}",
            json=body,
        )

    async def remove(self, activity_id: UUID, itinerary_id: str) -> dict[str, Any]:
        return await self._data(
            "DELETE", f"/trips/{itinerary_id}/activities/{activity_id}"
        )

    async def _data(self, method: str, path: str, **kwargs: Any) -> Any:
        body = await request(
            self._client,
            method,
            f"{self._prefix}{path}",
            unavailable="itinerary service unavailable",
            bad_response="bad response from itinerary service",
            **kwargs,
        )
        return body["data"] if isinstance(body, dict) and "data" in body else body
