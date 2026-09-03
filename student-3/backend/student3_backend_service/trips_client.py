from __future__ import annotations

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import (
    ApiError,
    bad_gateway,
    dependency_timeout,
    dependency_unavailable,
    not_found,
)
from .models import TransportTravellerTotal, TripSummary, TripTransportPin

_ITINERARY_FIELD = "itinerary"


class TripsApiClient:
    """This service's window onto Student 1's trips API.

    Two kinds of call live here, and they fail differently on purpose.

    *Reads that only decorate a page* -- listing trips, checking one exists --
    are best-effort: a transport catalogue is still useful when the trips
    service is down, so an unreachable dependency yields "unknown" rather than
    blocking. Only a definitive 404 means a trip does not exist.

    *Selections* are not. Which transport belongs to which trip is stored by
    Student 1, so a failed pin means nothing was saved, and a caller told
    otherwise would be lied to. Those methods raise.
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

    # ---------------------------------------------------------- selections
    #
    # Student 1 owns the trip-to-transport link, the way it owns the link to
    # accommodation and activities. This service reads and writes it there
    # rather than keeping a second copy.

    def list_trip_transport(self, trip_id: str) -> list[TripTransportPin]:
        """Transport selected for one trip. Raises if it cannot be read."""
        payload = self._require(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}/transport",
        )
        return self._parse(list[TripTransportPin], payload)

    def add_trip_transport(
        self,
        trip_id: str,
        transport_id: str,
        *,
        traveller_count: int,
        plan_status: str,
        notes: str | None = None,
    ) -> TripTransportPin:
        """Pin transport to a trip. Re-sending replaces rather than duplicates."""
        payload = self._require(
            "PUT",
            f"{self._api_prefix}/trips/{trip_id}/transport/{transport_id}",
            json={
                "traveller_count": traveller_count,
                "plan_status": plan_status,
                "notes": notes,
            },
        )
        return self._parse(TripTransportPin, payload)

    def remove_trip_transport(self, trip_id: str, transport_id: str) -> None:
        self._require(
            "DELETE",
            f"{self._api_prefix}/trips/{trip_id}/transport/{transport_id}",
        )

    def trips_for_transport(self, transport_id: str) -> list[TripSummary]:
        payload = self._require(
            "GET",
            f"{self._api_prefix}/transport/{transport_id}/trips",
        )
        return self._parse(list[TripSummary], payload)

    def traveller_totals(self) -> dict[str, int]:
        """Travellers selected per option, for deriving seats remaining.

        One request rather than one per option: a list page needs the figure
        for every option it renders.
        """
        payload = self._require(
            "GET",
            f"{self._api_prefix}/transport-traveller-totals",
        )
        totals = self._parse(list[TransportTravellerTotal], payload)
        return {row.transport_id: row.travellers for row in totals}

    def _require(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> object:
        """A call whose failure must not be mistaken for success."""
        try:
            response = self._client.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "The itinerary service did not respond in time.",
                [{"field": _ITINERARY_FIELD, "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                "The itinerary service is unavailable.",
                [{"field": _ITINERARY_FIELD, "issue": "connection failed"}],
            ) from exc

        if response.status_code == 404:
            raise not_found("Trip or transport selection", path.rsplit("/", 1)[-1])

        if response.is_error:
            raise self._translate(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise bad_gateway(
                "The itinerary service returned a malformed response.",
                [{"field": _ITINERARY_FIELD, "issue": "body was not JSON"}],
            ) from exc

        if not isinstance(payload, dict) or "data" not in payload:
            raise bad_gateway(
                "The itinerary service returned an unexpected envelope.",
                [{"field": _ITINERARY_FIELD, "issue": "no data envelope"}],
            )

        return payload["data"]

    @staticmethod
    def _parse(model: object, payload: object) -> object:
        try:
            return TypeAdapter(model).validate_python(payload)
        except ValidationError as exc:
            raise bad_gateway(
                "The itinerary service returned an unexpected shape.",
                [{"field": _ITINERARY_FIELD, "issue": "response did not validate"}],
            ) from exc

    @staticmethod
    def _translate(response: httpx.Response) -> ApiError:
        """Pass a validation refusal through; treat anything else as upstream."""
        try:
            body = response.json()
            error = body.get("error", {}) if isinstance(body, dict) else {}
        except ValueError:
            error = {}

        if response.status_code in {400, 409, 422}:
            return ApiError(
                status_code=response.status_code,
                code=str(error.get("code", "VALIDATION_ERROR")),
                message=str(
                    error.get("message", "The itinerary service refused the change."),
                ),
                details=error.get("details")
                or [{"field": _ITINERARY_FIELD, "issue": "rejected upstream"}],
            )

        return ApiError(
            status_code=502,
            code="BAD_GATEWAY",
            message="The itinerary service could not complete the change.",
            details=[{"field": _ITINERARY_FIELD, "issue": "unexpected status"}],
        )
