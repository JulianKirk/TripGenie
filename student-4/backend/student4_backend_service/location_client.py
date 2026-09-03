from __future__ import annotations

from collections.abc import Iterable  # noqa: TC003 (runtime client API)
from typing import TYPE_CHECKING, Any

import httpx

from .client import parse, request
from .config import Settings  # noqa: TC001 (runtime constructor contract)
from .schemas import CityPage, CityRecord, CountryPage, CountryRecord, DependencyHealth

if TYPE_CHECKING:
    from uuid import UUID

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

    async def health(self) -> DependencyHealth:
        return parse(
            DependencyHealth,
            await self._request("GET", "/health"),
            "bad response from location service",
        )

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

    async def vocabulary(self) -> tuple[list[str], list[str]]:
        if not self._loaded:
            await self._load()
        countries = sorted(self._country_ids)
        cities = sorted({city for _, city in self._city_ids})
        return countries, cities

    async def destination_filter(self, destination: str) -> dict[str, str] | None:
        if not self._loaded:
            await self._load()
        wanted = normalise(destination)
        country_id = self._country_ids.get(wanted)
        if country_id is not None:
            return {"country": self._names[country_id]}
        matches = [
            (owner, city_id)
            for (owner, city), city_id in self._city_ids.items()
            if city == wanted
        ]
        if len(matches) != 1:
            return None
        owner, city_id = matches[0]
        return {"country": self._names[owner], "city": self._names[city_id]}

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
        countries = await self._all_countries()
        cities = await self._all_cities()
        self._names = {row.id: row.name for row in countries} | {
            row.id: row.name for row in cities
        }
        self._country_ids = {normalise(row.name): row.id for row in countries}
        self._city_ids = {
            (row.country_id, normalise(row.name)): row.id for row in cities
        }
        self._loaded = True

    async def _all_countries(self) -> list[CountryRecord]:
        rows: list[CountryRecord] = []
        while True:
            body = await self._request(
                "GET",
                "/location/country",
                params={"limit": PAGE, "offset": len(rows)},
            )
            page = parse(CountryPage, body, "bad response from location service")
            rows.extend(page.countries)
            if len(rows) >= page.total or not page.countries:
                return rows

    async def _all_cities(self) -> list[CityRecord]:
        rows: list[CityRecord] = []
        while True:
            body = await self._request(
                "GET",
                "/location/city",
                params={"limit": PAGE, "offset": len(rows)},
            )
            page = parse(CityPage, body, "bad response from location service")
            rows.extend(page.cities)
            if len(rows) >= page.total or not page.cities:
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
