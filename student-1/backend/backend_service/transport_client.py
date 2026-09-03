"""Best-effort reads of transport details owned by Student 3.

A trip stores a transport option's id and the party size, and nothing else --
the route, the times and the price all belong to Student 3. The trip page has
to show a route rather than an identifier, so this is where that gets fetched.

Nothing here raises. A trip is still a trip when the transport service is down,
and a page that 500s because a route name could not be looked up would be worse
than one showing the selection without it. Callers get `None` and render a dash.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class TransportDetails(BaseModel):
    """The part of a transport option a trip page needs.

    `extra="ignore"` on purpose: Student 3 adding a field must not break the
    trip page.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    provider: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    duration_minutes: int = Field(gt=0)
    price: float = Field(ge=0)
    # Whether `price` multiplies by the party size. Whole-vehicle hire does not,
    # and without this the trip page would quietly multiply a per-vehicle rate
    # by the number of travellers.
    #
    # Lower case, unlike Student 4's PER_PERSON/FLAT_ADMISSION: Student 3's
    # enums are lower case throughout, and this has to match what that service
    # actually sends rather than what the neighbouring client happens to use.
    pricing_basis: Literal["per_traveller", "per_vehicle"] = "per_traveller"

    def cost_for(self, traveller_count: int) -> float:
        """What this option contributes for a party of `traveller_count`."""
        if self.pricing_basis == "per_vehicle":
            return self.price
        return round(self.price * traveller_count, 2)


class TransportClient:
    def __init__(self, settings: Any, *, transport: Any = None) -> None:
        self._client = httpx.Client(
            base_url=settings.transport_api_base_url,
            timeout=settings.transport_api_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def details(self, transport_ids: list[str]) -> dict[str, TransportDetails]:
        unique_ids = list(dict.fromkeys(transport_ids))
        if not unique_ids:
            return {}
        worker_count = min(len(unique_ids), 8)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            records = executor.map(self._one, unique_ids)
        found: dict[str, TransportDetails] = {}
        for transport_id, record in zip(unique_ids, records, strict=True):
            if record is not None:
                found[transport_id] = record
        return found

    def _one(self, transport_id: str) -> TransportDetails | None:
        try:
            response = self._client.get(f"/api/transport-options/{transport_id}")
        except httpx.RequestError:
            return None
        if not response.is_success:
            return None
        try:
            # Student 3 wraps payloads in a `data` envelope, unlike Student 4.
            payload = response.json()["data"]
            record = TransportDetails.model_validate(payload)
        except (KeyError, TypeError, ValueError, ValidationError):
            return None
        return record if record.id == transport_id else None
