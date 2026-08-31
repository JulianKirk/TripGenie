from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import (
    BackendHealthPayload,
    DataEnvelope,
    DeleteResponse,
    ErrorEnvelope,
    TransportOptionRecord,
    TransportPlanEntryRecord,
    TripTransportSummary,
)

T = TypeVar("T")

# Statuses the backend produces deliberately, carrying a structured envelope
# the frontend can render as field-level form errors.
HANDLED_ERROR_STATUSES = frozenset({400, 404, 409, 422, 502, 503, 504})

_BACKEND_FIELD = "backend"
_MALFORMED_ERROR = "Backend API returned a malformed error response."


class BackendApiClient:
    """Async HTTP client for the Student 3 backend API.

    The frontend never reaches the database service or the SQLite file; every
    read and write goes through the public ``/api`` surface.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_prefix = settings.backend_api_prefix
        self._client = httpx.AsyncClient(
            base_url=settings.backend_base_url,
            timeout=settings.backend_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> BackendHealthPayload:
        envelope = await self._request_model(
            "GET",
            "/health",
            expected_statuses={200},
            response_type=DataEnvelope[BackendHealthPayload],
            malformed_message="Backend API returned a malformed health response.",
        )
        return envelope.data

    async def ready(self) -> BackendHealthPayload:
        envelope = await self._request_model(
            "GET",
            "/ready",
            expected_statuses={200, 503},
            response_type=DataEnvelope[BackendHealthPayload],
            malformed_message="Backend API returned a malformed readiness response.",
        )
        return envelope.data

    async def list_transport_options(
        self,
        params: dict[str, str] | None = None,
    ) -> list[TransportOptionRecord]:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/transport-options",
            params=params or None,
            expected_statuses={200},
            response_type=DataEnvelope[list[TransportOptionRecord]],
            malformed_message="Backend API returned a malformed option list response.",
        )
        return envelope.data

    async def compare_transport_options(
        self,
        transport_ids: list[str],
    ) -> list[TransportOptionRecord]:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/transport-options/compare",
            params={"ids": ",".join(transport_ids)},
            expected_statuses={200},
            response_type=DataEnvelope[list[TransportOptionRecord]],
            malformed_message="Backend API returned a malformed comparison response.",
        )
        return envelope.data

    async def create_transport_option(
        self,
        payload: dict[str, object],
    ) -> TransportOptionRecord:
        envelope = await self._request_model(
            "POST",
            f"{self._api_prefix}/transport-options",
            json=payload,
            expected_statuses={201},
            response_type=DataEnvelope[TransportOptionRecord],
            malformed_message=(
                "Backend API returned a malformed option create response."
            ),
        )
        return envelope.data

    async def get_transport_option(self, transport_id: str) -> TransportOptionRecord:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/transport-options/{transport_id}",
            expected_statuses={200},
            response_type=DataEnvelope[TransportOptionRecord],
            malformed_message="Backend API returned a malformed option response.",
        )
        return envelope.data

    async def update_transport_option(
        self,
        transport_id: str,
        payload: dict[str, object],
    ) -> TransportOptionRecord:
        envelope = await self._request_model(
            "PATCH",
            f"{self._api_prefix}/transport-options/{transport_id}",
            json=payload,
            expected_statuses={200},
            response_type=DataEnvelope[TransportOptionRecord],
            malformed_message=(
                "Backend API returned a malformed option update response."
            ),
        )
        return envelope.data

    async def delete_transport_option(self, transport_id: str) -> DeleteResponse:
        envelope = await self._request_model(
            "DELETE",
            f"{self._api_prefix}/transport-options/{transport_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message=(
                "Backend API returned a malformed option delete response."
            ),
        )
        return envelope.data

    async def list_entries_for_option(
        self,
        transport_id: str,
    ) -> list[TransportPlanEntryRecord]:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/transport-options/{transport_id}/plan-entries",
            expected_statuses={200},
            response_type=DataEnvelope[list[TransportPlanEntryRecord]],
            malformed_message="Backend API returned a malformed entry list response.",
        )
        return envelope.data

    async def create_plan_entry(
        self,
        payload: dict[str, object],
    ) -> TransportPlanEntryRecord:
        envelope = await self._request_model(
            "POST",
            f"{self._api_prefix}/transport-bookings",
            json=payload,
            expected_statuses={201},
            response_type=DataEnvelope[TransportPlanEntryRecord],
            malformed_message="Backend API returned a malformed entry create response.",
        )
        return envelope.data

    async def get_plan_entry(self, booking_id: str) -> TransportPlanEntryRecord:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/transport-bookings/{booking_id}",
            expected_statuses={200},
            response_type=DataEnvelope[TransportPlanEntryRecord],
            malformed_message="Backend API returned a malformed entry response.",
        )
        return envelope.data

    async def update_plan_entry(
        self,
        booking_id: str,
        payload: dict[str, object],
    ) -> TransportPlanEntryRecord:
        envelope = await self._request_model(
            "PATCH",
            f"{self._api_prefix}/transport-bookings/{booking_id}",
            json=payload,
            expected_statuses={200},
            response_type=DataEnvelope[TransportPlanEntryRecord],
            malformed_message="Backend API returned a malformed entry update response.",
        )
        return envelope.data

    async def delete_plan_entry(self, booking_id: str) -> DeleteResponse:
        envelope = await self._request_model(
            "DELETE",
            f"{self._api_prefix}/transport-bookings/{booking_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message="Backend API returned a malformed entry delete response.",
        )
        return envelope.data

    async def trip_transport(self, trip_id: str) -> TripTransportSummary:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}/transport",
            expected_statuses={200},
            response_type=DataEnvelope[TripTransportSummary],
            malformed_message=(
                "Backend API returned a malformed trip transport response."
            ),
        )
        return envelope.data

    async def _request_model(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        expected_statuses: set[int],
        response_type: Any,
        malformed_message: str,
    ) -> T:
        response = await self._send(method, path, params=params, json=json)
        if response.status_code not in expected_statuses:
            self._raise_error_response(response)

        payload = self._decode_json(response, malformed_message)
        try:
            return TypeAdapter(response_type).validate_python(payload)
        except ValidationError as exc:
            raise bad_gateway(
                malformed_message,
                [
                    {
                        "field": _BACKEND_FIELD,
                        "issue": "response body did not match the expected schema",
                    },
                ],
            ) from exc

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            return await self._client.request(method, path, params=params, json=json)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "Backend API did not respond before the configured timeout.",
                [{"field": _BACKEND_FIELD, "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            raise bad_gateway(
                "Backend API returned an invalid HTTP response.",
                [
                    {
                        "field": _BACKEND_FIELD,
                        "issue": "dependency returned invalid HTTP",
                    },
                ],
            ) from exc
        except httpx.NetworkError as exc:
            raise dependency_unavailable(
                "Backend API is unavailable.",
                [{"field": _BACKEND_FIELD, "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                "Backend API request failed.",
                [
                    {
                        "field": _BACKEND_FIELD,
                        "issue": "request could not be completed",
                    },
                ],
            ) from exc

    @staticmethod
    def _decode_json(response: httpx.Response, message: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise bad_gateway(
                message,
                [
                    {
                        "field": _BACKEND_FIELD,
                        "issue": "response body was not valid JSON",
                    },
                ],
            ) from exc

    def _raise_error_response(self, response: httpx.Response) -> None:
        if response.status_code in HANDLED_ERROR_STATUSES:
            payload = self._decode_json(response, _MALFORMED_ERROR)
            try:
                envelope = ErrorEnvelope.model_validate(payload)
            except ValidationError as exc:
                raise bad_gateway(
                    _MALFORMED_ERROR,
                    [
                        {
                            "field": _BACKEND_FIELD,
                            "issue": "error body did not match the expected schema",
                        },
                    ],
                ) from exc

            raise ApiError(
                status_code=response.status_code,
                code=envelope.error.code,
                message=envelope.error.message,
                details=[
                    detail.model_dump(mode="json") for detail in envelope.error.details
                ],
            )

        if response.status_code >= 500:
            raise bad_gateway(
                "Backend API failed while processing the request.",
                [
                    {
                        "field": _BACKEND_FIELD,
                        "issue": f"dependency returned HTTP {response.status_code}",
                    },
                ],
            )

        raise bad_gateway(
            "Backend API returned an unexpected response.",
            [
                {
                    "field": _BACKEND_FIELD,
                    "issue": f"unexpected HTTP {response.status_code}",
                },
            ],
        )
