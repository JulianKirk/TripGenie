"""The database service, as this service sees it.

The only module that knows the database service speaks HTTP. It owns the whole
502/503 mapping from ../../docs/backend-service-api.md, so the routers never
handle an `httpx` type: a call either returns a decoded body or raises the
`HTTPException` the doc documents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from backend_service.config import Settings

T = TypeVar("T", bound=BaseModel)

PATH = "/internal/users"
UNAVAILABLE = "database service unavailable"
BAD_RESPONSE = "bad response from database service"


class DatabaseClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        # `transport` is a test seam: the tests point it at the database app
        # over ASGI, or at a mock for the failures a real one will not produce
        # on demand.
        self._client = httpx.AsyncClient(
            base_url=settings.database_url,
            timeout=settings.db_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        return await self.request("GET", "/health")

    async def get(self, user_id: UUID) -> dict[str, Any]:
        return await self.request("GET", f"{PATH}/{user_id}")

    async def by_username(self, username: str) -> dict[str, Any]:
        """The lookup a login is. Answers the list shape, matches or not."""
        return await self.request("GET", PATH, params={"username": username})

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", PATH, json=body)

    async def update(self, user_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PUT", f"{PATH}/{user_id}", json=body)

    async def delete(self, user_id: UUID) -> None:
        await self.request("DELETE", f"{PATH}/{user_id}")

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await request(
            self._client, method, path, unavailable=UNAVAILABLE, **kwargs
        )


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    unavailable: str = UNAVAILABLE,
    **kwargs: Any,
) -> Any:
    """The decoded response body, or the documented 502/503.

    A 4xx is the upstream service answering correctly about a bad request, so
    it is re-raised unchanged -- body and all -- and reaches the caller as the
    same 400, 404 or 409. Anything else that is not a usable 2xx is this
    service failing to reach its data, which is a 502 or a 503.
    """
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.RequestError as exc:  # covers TimeoutException
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, unavailable) from exc

    if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE)

    # 204 is the documented answer to a DELETE and has no body to decode.
    if response.status_code == status.HTTP_204_NO_CONTENT:
        return None

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE) from exc

    if response.is_client_error:
        # `detail` is what every documented error body carries; falling back to
        # the whole body keeps an unexpected shape readable.
        detail = body.get("detail", body) if isinstance(body, dict) else body
        raise HTTPException(response.status_code, detail)

    return body


def parse(model: type[T], body: Any) -> T:
    """A database service response, as the message this service publishes.

    The two services declare that message separately (see schemas.py), so this
    is where drift surfaces: a response that does not fit the published
    contract is the documented 502, not a 500.
    """
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BAD_RESPONSE) from exc
