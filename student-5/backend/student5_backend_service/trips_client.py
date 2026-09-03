from __future__ import annotations

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import bad_gateway, dependency_error, invalid_trip
from .models import TripRecord


class TripsApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._prefix = settings.trips_api_prefix
        self._client = httpx.Client(
            base_url=settings.trips_api_base_url,
            timeout=settings.trips_api_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def list_trips(self) -> list[TripRecord]:
        try:
            response = self._client.get(f"{self._prefix}/trips")
        except httpx.RequestError as exc:
            raise dependency_error("trips", str(exc)) from exc
        if response.status_code != 200:
            raise dependency_error("trips", f"HTTP {response.status_code}")
        try:
            payload = response.json()["data"]
            if not isinstance(payload, list):
                raise TypeError("data must be a list")
            return [TripRecord.model_validate(item) for item in payload]
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise bad_gateway("trips", str(exc)) from exc

    def get_trip(self, trip_id: str) -> TripRecord | None:
        try:
            response = self._client.get(f"{self._prefix}/trips/{trip_id}")
        except httpx.RequestError:
            return None
        if response.status_code == 404:
            raise invalid_trip(trip_id)
        if response.status_code != 200:
            return None
        try:
            return TripRecord.model_validate(response.json()["data"])
        except (KeyError, TypeError, ValueError, ValidationError):
            return None
