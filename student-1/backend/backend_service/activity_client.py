"""Best-effort reads of activity details owned by Student 4."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


class ActivityDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: str
    name: str
    price: Annotated[str, StringConstraints(pattern=r"^\d+\.\d{2}$")]
    pricing_basis: Literal["PER_PERSON", "FLAT_ADMISSION"]
    duration_minutes: int = Field(gt=0)


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
        found: dict[str, ActivityDetails] = {}
        for activity_id in dict.fromkeys(activity_ids):
            record = self._one(activity_id)
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
