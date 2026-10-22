"""The shared host-run Multi-Agent Server (Release 2), as this service sees it.

The server runs the Planner -> Worker -> Reviewer workflow in the background and
holds each run until a human decides. This client only starts runs, reads them
and forwards the decision. Run records come back as plain dicts because the
server owns their shape; `agent_runs` turns them into this service's view.

Failures use the same documented statuses as every other upstream here: the
server being down or too slow is a 503, a reply that is not the run contract is
a 502. A handful of the server's own errors tell the caller something it can act
on (unknown run, run not awaiting review, run limit), so those are passed on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException, status

if TYPE_CHECKING:
    from backend_service.config import Settings

UNAVAILABLE = "The Multi-Agent Server is unavailable."
TIMED_OUT = "The Multi-Agent Server timed out."
BAD_RESPONSE = "The Multi-Agent Server returned an invalid response."
# Server errors worth passing on: each tells the caller something it can act on.
PRESERVED_ERRORS = {
    404: {"RUN_NOT_FOUND"},
    409: {"RUN_NOT_AWAITING_REVIEW"},
    422: {"VALIDATION_ERROR"},
    503: {"RUN_LIMIT_REACHED"},
}


class MultiAgentClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        self.enabled = settings.multi_agent_enabled
        # `transport` is the same test seam the other clients use.
        self._client = httpx.AsyncClient(
            base_url=settings.multi_agent_base_url,
            timeout=httpx.Timeout(settings.multi_agent_timeout, connect=3.0),
            transport=transport,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/runs", body)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/runs/{run_id}")

    async def review(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/runs/{run_id}/review", body)

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=body)
        except httpx.TimeoutException as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, TIMED_OUT) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, UNAVAILABLE
            ) from exc

        if response.is_error:
            _raise_upstream_error(response)
        try:
            data = response.json()["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE) from exc
        if not isinstance(data, dict):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)
        return data


def _raise_upstream_error(response: httpx.Response) -> None:
    try:
        error = response.json()["error"]
        code = str(error["code"])
        message = str(error["message"])
    except (ValueError, KeyError, TypeError):
        code, message = "", ""
    if code in PRESERVED_ERRORS.get(response.status_code, set()):
        raise HTTPException(response.status_code, f"{code}: {message}")
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)
