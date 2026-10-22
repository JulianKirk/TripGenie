"""HTTP boundary to the host-run Multi-Agent Server; requests are never retried."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException

if TYPE_CHECKING:
    from .config import Settings


class PlannerClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.enabled = settings.multi_agent_enabled
        self.client = httpx.AsyncClient(
            base_url=settings.multi_agent_url,
            timeout=settings.multi_agent_timeout,
            transport=transport,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> object:
        if not self.enabled:
            raise HTTPException(
                503, "Smart Planner is disabled. Activity browsing is still available."
            )
        try:
            response = await self.client.request(method, path, json=body)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                504,
                (
                    "Smart Planner timed out. The request may have been received; "
                    "refresh the run before submitting again."
                ),
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                503,
                "Smart Planner is unavailable. Activity browsing is still available.",
            ) from exc
        if response.status_code not in {200, 202}:
            messages = {
                404: "Smart Planner run not found.",
                409: (
                    "This run is no longer awaiting review. Refresh to see its "
                    "current state."
                ),
                422: "Smart Planner could not accept that request.",
                503: "Smart Planner is unavailable or busy. Please try again later.",
            }
            code = response.status_code if response.status_code in messages else 502
            raise HTTPException(
                code,
                messages.get(code, "Smart Planner returned an unexpected response."),
            )
        try:
            payload: object = response.json()
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
        except ValueError:
            pass
        raise HTTPException(502, "Smart Planner returned an invalid response.")
