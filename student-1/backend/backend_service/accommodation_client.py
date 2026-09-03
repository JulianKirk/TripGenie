"""Student 2's accommodation service, as this service sees it.

A trip stores an accommodation's id and nothing else -- the name, the nightly
rate and everything else about it belong to student 2. The trip page has to
show a name rather than a UUID, so this is where that gets fetched.

The call goes out from here rather than from the frontend so that the frontend
keeps talking to exactly one backend, the same rule student 2 follows in the
other direction.

Nothing here raises. A trip is still a trip when the accommodation service is
down, and a page that 500s because a name could not be looked up would be worse
than one showing the stay without it. Callers get `None` and render a dash.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class AccommodationClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        self._client = httpx.Client(
            base_url=settings.accommodation_api_base_url,
            timeout=settings.accommodation_api_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def details(self, accommodation_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Name and nightly rate per id, skipping any the service cannot answer
        for.

        ponytail: one request per accommodation. N is the accommodations on one
        trip, so it is small, and student 2 publishes no batch lookup -- its
        QUERY endpoint filters, it does not fetch a set of ids. Ask for a batch
        endpoint there before optimising here.
        """
        found: dict[str, dict[str, Any]] = {}
        for accommodation_id in dict.fromkeys(accommodation_ids):
            record = self._one(accommodation_id)
            if record is not None:
                found[accommodation_id] = record
        return found

    def _one(self, accommodation_id: str) -> dict[str, Any] | None:
        try:
            response = self._client.get(f"/accommodation/{accommodation_id}")
        except httpx.RequestError:
            return None
        if not response.is_success:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        return {
            "name": body.get("name"),
            "price_per_night": body.get("price_per_night"),
        }
