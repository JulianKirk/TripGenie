"""Best-effort reads of activity details owned by Student 4."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


class ActivityLocation(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    country: str | None = None
    city: str | None = None
    street: str | None = None
    street_number: int | None = None

    def label(self) -> str | None:
        parts: list[str] = []
        if self.street:
            street = self.street
            if self.street_number is not None:
                street = f"{self.street_number} {street}"
            parts.append(street)
        parts.extend(value for value in (self.city, self.country) if value)
        return ", ".join(parts) or None


class ActivityDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: str
    name: str
    price: Annotated[str, StringConstraints(pattern=r"^\d+\.\d{2}$")]
    pricing_basis: Literal["PER_PERSON", "FLAT_ADMISSION"]
    duration_minutes: int = Field(gt=0)
    location_details: ActivityLocation | None = None


class ActivityClient:
    def __init__(self, settings: Any, *, transport: Any = None) -> None:
        self._client = httpx.Client(
            base_url=settings.activity_api_base_url,
            timeout=settings.activity_api_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def details(self, activity_ids: list[str]) -> dict[str, ActivityDetails]:
        unique_ids = list(dict.fromkeys(activity_ids))
        if not unique_ids:
            return {}
        worker_count = min(len(unique_ids), 8)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            records = executor.map(self._one, unique_ids)
        found: dict[str, ActivityDetails] = {}
        for activity_id, record in zip(unique_ids, records, strict=True):
            if record is not None:
                found[activity_id] = record
        return found

    def _one(self, activity_id: str) -> ActivityDetails | None:
        try:
            response = self._client.get(f"/activity/{activity_id}")
        except httpx.RequestError:
            return None
        if not response.is_success:
            return None
        try:
            record = ActivityDetails.model_validate(response.json())
        except (ValueError, ValidationError):
            return None
        return record if record.id == activity_id else None
