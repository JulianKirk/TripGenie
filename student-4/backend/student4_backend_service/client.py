from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID  # noqa: TC003 (runtime client API)

import httpx
from fastapi import HTTPException, status
from pydantic import TypeAdapter, ValidationError

from .config import Settings  # noqa: TC001 (runtime constructor contract)
from .schemas import (
    CategoryList,
    DeleteResponse,
    DependencyHealth,
    InternalActivity,
    InternalQueryResponse,
)

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")
PATH = "/internal/activity"


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    unavailable: str,
    bad_response: str,
    client_error_detail: Callable[[Any], Any] | None = None,
    **kwargs: Any,
) -> Any:
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.RequestError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, unavailable) from exc
    if response.status_code >= 500:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, bad_response)
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, bad_response) from exc
    if response.is_client_error:
        detail = (
            client_error_detail(body)
            if client_error_detail is not None
            else _error_detail(body)
        )
        raise HTTPException(response.status_code, detail)
    return body


def _error_detail(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return body.get("detail", body)


def parse(
    model: type[T],
    body: Any,
    message: str = "bad response from database service",
) -> T:
    try:
        return TypeAdapter(model).validate_python(body)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, message) from exc


class DatabaseClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.database_url,
            timeout=settings.db_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> DependencyHealth:
        return parse(DependencyHealth, await self._raw("GET", "/internal/health"))

    async def categories(self) -> CategoryList:
        return parse(CategoryList, await self._raw("GET", f"{PATH}/categories"))

    async def get(self, activity_id: UUID) -> InternalActivity:
        return parse(InternalActivity, await self._raw("GET", f"{PATH}/{activity_id}"))

    async def create(self, body: dict[str, Any]) -> InternalActivity:
        return parse(InternalActivity, await self._raw("POST", PATH, json=body))

    async def replace(
        self, activity_id: UUID, body: dict[str, Any]
    ) -> InternalActivity:
        return parse(
            InternalActivity,
            await self._raw("PUT", f"{PATH}/{activity_id}", json=body),
        )

    async def delete(self, activity_id: UUID) -> DeleteResponse:
        return parse(DeleteResponse, await self._raw("DELETE", f"{PATH}/{activity_id}"))

    async def query(self, body: dict[str, Any]) -> InternalQueryResponse:
        return parse(InternalQueryResponse, await self._raw("QUERY", PATH, json=body))

    async def _raw(self, method: str, path: str, **kwargs: Any) -> Any:
        return await request(
            self._client,
            method,
            path,
            unavailable="database service unavailable",
            bad_response="bad response from database service",
            **kwargs,
        )
