from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import (
    AiSuggestionsResponse,
    BackendHealthPayload,
    DataEnvelope,
    DeleteResponse,
    ErrorEnvelope,
    ItineraryItemRecord,
    TripDetail,
    TripRecord,
)

T = TypeVar("T")
HANDLED_ERROR_STATUSES = {400, 404, 409, 422, 502, 503, 504}


class BackendApiClient:
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

    async def list_trips(self) -> list[TripRecord]:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/trips",
            expected_statuses={200},
            response_type=DataEnvelope[list[TripRecord]],
            malformed_message="Backend API returned a malformed trip list response.",
        )
        return envelope.data

    async def generate_ai_suggestions(
        self,
        trip_id: str,
        payload: dict[str, object],
    ) -> AiSuggestionsResponse:
        envelope = await self._request_model(
            "POST",
            f"{self._api_prefix}/trips/{trip_id}/ai-suggestions",
            json=payload,
            expected_statuses={200},
            response_type=DataEnvelope[AiSuggestionsResponse],
            malformed_message=(
                "Backend API returned a malformed AI suggestion response."
            ),
        )
        return envelope.data

    async def create_trip(self, payload: dict[str, object]) -> TripDetail:
        envelope = await self._request_model(
            "POST",
            f"{self._api_prefix}/trips",
            json=payload,
            expected_statuses={201},
            response_type=DataEnvelope[TripDetail],
            malformed_message="Backend API returned a malformed trip create response.",
        )
        return envelope.data

    async def get_trip(self, trip_id: str) -> TripDetail:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}",
            expected_statuses={200},
            response_type=DataEnvelope[TripDetail],
            malformed_message="Backend API returned a malformed trip response.",
        )
        return envelope.data

    async def update_trip(self, trip_id: str, payload: dict[str, object]) -> TripDetail:
        envelope = await self._request_model(
            "PATCH",
            f"{self._api_prefix}/trips/{trip_id}",
            json=payload,
            expected_statuses={200},
            response_type=DataEnvelope[TripDetail],
            malformed_message="Backend API returned a malformed trip update response.",
        )
        return envelope.data

    async def delete_trip(self, trip_id: str) -> DeleteResponse:
        envelope = await self._request_model(
            "DELETE",
            f"{self._api_prefix}/trips/{trip_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message="Backend API returned a malformed trip delete response.",
        )
        return envelope.data

    async def create_itinerary_item(
        self,
        trip_id: str,
        payload: dict[str, object],
    ) -> ItineraryItemRecord:
        envelope = await self._request_model(
            "POST",
            f"{self._api_prefix}/trips/{trip_id}/itinerary-items",
            json=payload,
            expected_statuses={201},
            response_type=DataEnvelope[ItineraryItemRecord],
            malformed_message=(
                "Backend API returned a malformed itinerary create response."
            ),
        )
        return envelope.data

    async def get_itinerary_item(self, item_id: str) -> ItineraryItemRecord:
        envelope = await self._request_model(
            "GET",
            f"{self._api_prefix}/itinerary-items/{item_id}",
            expected_statuses={200},
            response_type=DataEnvelope[ItineraryItemRecord],
            malformed_message="Backend API returned a malformed itinerary response.",
        )
        return envelope.data

    async def update_itinerary_item(
        self,
        item_id: str,
        payload: dict[str, object],
    ) -> ItineraryItemRecord:
        envelope = await self._request_model(
            "PATCH",
            f"{self._api_prefix}/itinerary-items/{item_id}",
            json=payload,
            expected_statuses={200},
            response_type=DataEnvelope[ItineraryItemRecord],
            malformed_message=(
                "Backend API returned a malformed itinerary update response."
            ),
        )
        return envelope.data

    async def delete_itinerary_item(self, item_id: str) -> DeleteResponse:
        envelope = await self._request_model(
            "DELETE",
            f"{self._api_prefix}/itinerary-items/{item_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message=(
                "Backend API returned a malformed itinerary delete response."
            ),
        )
        return envelope.data

    async def _request_model(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expected_statuses: set[int],
        response_type: Any,
        malformed_message: str,
    ) -> T:
        response = await self._send(method, path, json=json)
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
                        "field": "backend",
                        "issue": "response body did not match the expected schema",
                    },
                ],
            ) from exc

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            return await self._client.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "Backend API did not respond before the configured timeout.",
                [{"field": "backend", "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            raise bad_gateway(
                "Backend API returned an invalid HTTP response.",
                [{"field": "backend", "issue": "dependency returned invalid HTTP"}],
            ) from exc
        except httpx.NetworkError as exc:
            raise dependency_unavailable(
                "Backend API is unavailable.",
                [{"field": "backend", "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError:
            raise dependency_unavailable(
                "Backend API request failed.",
                [{"field": "backend", "issue": "request could not be completed"}],
            ) from None

    @staticmethod
    def _decode_json(response: httpx.Response, malformed_message: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise bad_gateway(
                malformed_message,
                [{"field": "backend", "issue": "response body was not valid JSON"}],
            ) from exc

    def _raise_error_response(self, response: httpx.Response) -> None:
        if response.status_code not in HANDLED_ERROR_STATUSES:
            raise bad_gateway(
                "Backend API returned an unexpected status code.",
                [
                    {
                        "field": "backend",
                        "issue": f"unexpected status {response.status_code}",
                    },
                ],
            )

        payload = self._decode_json(
            response,
            "Backend API returned a malformed error response.",
        )
        try:
            error = TypeAdapter(ErrorEnvelope).validate_python(payload).error
        except ValidationError as exc:
            raise bad_gateway(
                "Backend API returned a malformed error response.",
                [{"field": "backend", "issue": "error body did not match schema"}],
            ) from exc

        raise ApiError(
            status_code=response.status_code,
            code=error.code,
            message=error.message,
            details=[detail.model_dump(mode="json") for detail in error.details],
        )
