from __future__ import annotations

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .models import TripSummary


class TripsApiClient:
    """Best-effort existence check against Student 1's trips API.

    Student 1 owns trips, so this service can only ask. The check is advisory by
    design: a transport plan is still useful when the trips service is down, so
    an unreachable or erroring dependency yields "unknown" rather than blocking
    the write. Only a definitive 404 means the trip does not exist.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_prefix = settings.trips_api_prefix
        self._client = httpx.Client(
            base_url=settings.trips_api_base_url,
            timeout=settings.trips_api_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def list_trips(self) -> list[TripSummary] | None:
        """Trips Student 1 knows about, or None when that cannot be determined.

        None and an empty list mean different things: None is "the lookup
        failed", [] is "there genuinely are no trips". Callers need to tell them
        apart to decide whether to offer a picker or a free-text field.
        """
        try:
            response = self._client.request("GET", f"{self._api_prefix}/trips")
        except httpx.RequestError:
            return None

        if response.status_code != 200:
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        if not isinstance(payload, dict) or "data" not in payload:
            return None

        try:
            return TypeAdapter(list[TripSummary]).validate_python(payload["data"])
        except ValidationError:
            return None

    def trip_exists(self, trip_id: str) -> bool | None:
        """True, False, or None when the answer cannot be determined."""
        try:
            response = self._client.request(
                "GET",
                f"{self._api_prefix}/trips/{trip_id}",
            )
        except httpx.RequestError:
            return None

        if response.status_code == 200:
            return True

        if response.status_code == 404:
            return False

        return None
