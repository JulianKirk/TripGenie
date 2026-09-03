from __future__ import annotations

from collections.abc import Iterable  # noqa: TC003 (runtime client API)
from typing import Any
from uuid import UUID

import httpx

from .client import request
from .config import Settings  # noqa: TC001 (runtime constructor contract)

PAGE = 100


def normalise(name: str) -> str:
    return name.strip().lower()


class LocationClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.location_url,
            timeout=settings.location_timeout,
            transport=transport,
        )
        self._loaded = False
        self._names: dict[UUID, str] = {}
        self._country_ids: dict[str, UUID] = {}
        self._city_ids: dict[tuple[UUID, str], UUID] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def ids(
        self, country: str, city: str | None
    ) -> tuple[UUID, UUID | None] | None:
        if not self._loaded:
            await self._load()
        found = self._lookup(country, city)
        if found is None:
            await self._load()
            found = self._lookup(country, city)
        return found

    async def names(self, ids: Iterable[UUID]) -> dict[UUID, str]:
        wanted = set(ids)
        if not self._loaded or not wanted <= self._names.keys():
            await self._load()
        return {item: self._names[item] for item in wanted if item in self._names}

    def _lookup(
        self, country: str, city: str | None
    ) -> tuple[UUID, UUID | None] | None:
        country_id = self._country_ids.get(normalise(country))
        if country_id is None:
            return None
        if city is None:
            return country_id, None
        city_id = self._city_ids.get((country_id, normalise(city)))
        return (country_id, city_id) if city_id is not None else None

    async def _load(self) -> None:
        countries = await self._all("/location/country", "countries")
        cities = await self._all("/location/city", "cities")
        self._names = {UUID(row["id"]): row["name"] for row in countries} | {
            UUID(row["id"]): row["name"] for row in cities
        }
        self._country_ids = {
            normalise(row["name"]): UUID(row["id"]) for row in countries
        }
        self._city_ids = {
            (UUID(row["country_id"]), normalise(row["name"])): UUID(row["id"])
            for row in cities
        }
        self._loaded = True

    async def _all(self, path: str, key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            body = await self._request(
                "GET", path, params={"limit": PAGE, "offset": len(rows)}
            )
            page = body[key]
            rows.extend(page)
            if len(rows) >= body["total"] or not page:
                return rows

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await request(
            self._client,
            method,
            path,
            unavailable="location service unavailable",
            bad_response="bad response from location service",
            **kwargs,
        )
