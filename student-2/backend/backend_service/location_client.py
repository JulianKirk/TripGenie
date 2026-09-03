"""The shared reference service, as this service sees it.

Country and city are reference data every micro-service needs, so they live in
the shared service rather than in the accommodation database. What this service
stores is ids; what it publishes is names. This module is the only place that
knows the difference, and the only place that knows the shared service speaks
HTTP.

Failures map through the same `client.request` the database service uses, so a
shared-service outage is the documented 503 and a malformed answer is a 502.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx

from backend_service.client import request

if TYPE_CHECKING:
    from collections.abc import Iterable

    from backend_service.config import Settings

UNAVAILABLE = "location service unavailable"
BAD_RESPONSE = "bad response from location service"
# The shared service caps a page at 100, so this is the fewest requests a full
# list can take.
PAGE = 100


def normalise(name: str) -> str:
    """The form the shared service stores names in. Matching on anything else
    would make "Sydney" and "sydney" two different places to this client."""
    return name.strip().lower()


class LocationClient:
    """Name-to-id and id-to-name over the shared reference service.

    Both reference lists are held in memory and refetched on a miss.

    ponytail: a whole-list cache, not a per-name query and not a TTL. The lists
    are a few dozen near-static rows, and a place that is genuinely new costs
    one refetch to learn. Switch to a per-name QUERY when the lists stop fitting
    in a couple of pages, and add a lock around the refetch if a stampede of
    simultaneous misses ever shows up in a trace -- today a duplicate refetch is
    just a wasted call.
    """

    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        # `transport` is the same test seam the database client uses.
        self._client = httpx.AsyncClient(
            base_url=settings.location_url,
            timeout=settings.location_timeout,
            transport=transport,
        )
        self._loaded = False
        # One id-to-name map for both kinds: the shared service derives an id
        # from the name it belongs to, so a country id and a city id can never
        # collide.
        self._names: dict[UUID, str] = {}
        self._country_ids: dict[str, UUID] = {}
        # Keyed by country, because "sydney" alone names two places.
        self._city_ids: dict[tuple[UUID, str], UUID] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def ids(
        self, country: str | None, city: str | None
    ) -> tuple[UUID | None, UUID | None] | None:
        """The ids for a named place, or `None` when no such place exists.

        `None` is not an error: a search for accommodation in Narnia is a
        well-formed question with an empty answer, and the route turns it into
        one. `(None, None)` means the caller named no place at all.
        """
        if country is None:
            return None, None
        found = await self._find(country, city)
        if found is None:
            # The place may simply be newer than the cache. One refetch tells
            # us which.
            await self._load()
            found = self._lookup(country, city)
        return found

    async def countries(self) -> list[str]:
        """Every country the shared service knows, sorted.

        The ask box's prompt needs the vocabulary of real place names, and this
        client is already holding it. No extra call in the warm case.
        """
        if not self._loaded:
            await self._load()
        return sorted(self._country_ids)

    async def cities(self) -> list[str]:
        """Every city the shared service knows, sorted. Same reason as
        `countries`: the ask box constrains the model to real place names."""
        if not self._loaded:
            await self._load()
        return sorted({city for _, city in self._city_ids})

    def country_of(self, city: str) -> str | None:
        """The country a city is in, when exactly one country has a city by
        that name.

        `None` for a city nobody has, and also for an ambiguous one -- "sydney"
        is in two countries, and picking one of them for a traveller who did not
        say is worse than not filtering on the place at all.

        Sync, and reads the cache without refilling it: the only caller has just
        been handed a name out of that same cache.
        """
        found = [country for country, name in self._city_ids if name == normalise(city)]
        return self._names[found[0]] if len(found) == 1 else None

    async def names(self, ids: Iterable[UUID]) -> dict[UUID, str]:
        """The name for each id, for the ids that have one.

        Takes the whole batch rather than one id at a time so a page of 100
        results costs at most one refetch, not 100. An id with no name is left
        out: the row still exists and still returns, it just cannot say where it
        is -- better than failing the whole response over one stale reference.
        """
        wanted = set(ids)
        if not wanted:
            # A response with no places in it must not cost a call.
            return {}
        if not self._loaded or not wanted <= self._names.keys():
            await self._load()
        return {place: self._names[place] for place in wanted if place in self._names}

    async def _find(
        self, country: str, city: str | None
    ) -> tuple[UUID | None, UUID | None] | None:
        if not self._loaded:
            await self._load()
        return self._lookup(country, city)

    def _lookup(
        self, country: str, city: str | None
    ) -> tuple[UUID | None, UUID | None] | None:
        country_id = self._country_ids.get(normalise(country))
        if country_id is None:
            return None
        if city is None:
            return country_id, None
        city_id = self._city_ids.get((country_id, normalise(city)))
        if city_id is None:
            return None
        return country_id, city_id

    async def _load(self) -> None:
        countries = await self._all("/location/country", "countries")
        cities = await self._all("/location/city", "cities")
        self._names = {UUID(row["id"]): row["name"] for row in countries} | {
            UUID(row["id"]): row["name"] for row in cities
        }
        self._country_ids = {row["name"]: UUID(row["id"]) for row in countries}
        self._city_ids = {
            (UUID(row["country_id"]), row["name"]): UUID(row["id"]) for row in cities
        }
        self._loaded = True

    async def _all(self, path: str, key: str) -> list[dict[str, Any]]:
        """Every row, paged. The shared service caps a page, so "the whole
        list" is however many requests that takes."""
        rows: list[dict[str, Any]] = []
        while True:
            body = await self._request(
                "GET", path, params={"limit": PAGE, "offset": len(rows)}
            )
            rows.extend(body[key])
            if len(rows) >= body["total"] or not body[key]:
                return rows

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await request(
            self._client,
            method,
            path,
            unavailable=UNAVAILABLE,
            bad_response=BAD_RESPONSE,
            **kwargs,
        )
