from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import (
    AvailabilityStatus,
    DatabaseHealthPayload,
    DataEnvelope,
    DeleteResponse,
    ErrorEnvelope,
    TransportOptionCreate,
    TransportOptionRecord,
    TransportOptionUpdate,
    TransportType,
)

T = TypeVar("T")

HANDLED_ERROR_STATUSES = frozenset({400, 404, 409, 422, 503})

_MALFORMED_ERROR = "Database API returned a malformed error response."
_DEPENDENCY_FIELD = "database"


class DatabaseApiClient:
    """HTTP client for the Student 3 database API.

    The backend never opens the SQLite file; every read and write goes through
    these calls. Dependency failures are translated into the shared error
    envelope so callers never see a raw httpx exception.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_prefix = settings.database_api_prefix
        self._client = httpx.Client(
            base_url=settings.database_api_base_url,
            timeout=settings.database_api_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def health(self) -> DatabaseHealthPayload:
        return self._request_model(
            "GET",
            f"{self._api_prefix}/health",
            expected_statuses={200},
            response_type=DatabaseHealthPayload,
            malformed_message="Database API returned a malformed health response.",
        )

    def list_transport_options(
        self,
        *,
        transport_type: TransportType | None = None,
        provider: str | None = None,
        origin: str | None = None,
        destination: str | None = None,
        availability_status: AvailabilityStatus | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        departure_from: str | None = None,
        departure_to: str | None = None,
    ) -> list[TransportOptionRecord]:
        params: dict[str, str] = {}
        if transport_type is not None:
            params["type"] = transport_type.value
        if provider is not None:
            params["provider"] = provider
        if origin is not None:
            params["origin"] = origin
        if destination is not None:
            params["destination"] = destination
        if availability_status is not None:
            params["availability_status"] = availability_status.value
        if min_price is not None:
            params["min_price"] = str(min_price)
        if max_price is not None:
            params["max_price"] = str(max_price)
        if departure_from is not None:
            params["departure_from"] = departure_from
        if departure_to is not None:
            params["departure_to"] = departure_to

        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/transport-options",
            params=params or None,
            expected_statuses={200},
            response_type=DataEnvelope[list[TransportOptionRecord]],
            malformed_message="Database API returned a malformed option list response.",
        )
        return envelope.data

    def create_transport_option(
        self,
        payload: TransportOptionCreate,
    ) -> TransportOptionRecord:
        envelope = self._request_model(
            "POST",
            f"{self._api_prefix}/transport-options",
            json=payload.model_dump(mode="json", exclude_none=True),
            expected_statuses={201},
            response_type=DataEnvelope[TransportOptionRecord],
            malformed_message=(
                "Database API returned a malformed option create response."
            ),
        )
        return envelope.data

    def get_transport_option(self, transport_id: str) -> TransportOptionRecord:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/transport-options/{transport_id}",
            expected_statuses={200},
            response_type=DataEnvelope[TransportOptionRecord],
            malformed_message="Database API returned a malformed option response.",
        )
        return envelope.data

    def update_transport_option(
        self,
        transport_id: str,
        payload: TransportOptionUpdate,
    ) -> TransportOptionRecord:
        envelope = self._request_model(
            "PATCH",
            f"{self._api_prefix}/transport-options/{transport_id}",
            json=payload.model_dump(mode="json", exclude_unset=True),
            expected_statuses={200},
            response_type=DataEnvelope[TransportOptionRecord],
            malformed_message=(
                "Database API returned a malformed option update response."
            ),
        )
        return envelope.data

    def delete_transport_option(self, transport_id: str) -> DeleteResponse:
        envelope = self._request_model(
            "DELETE",
            f"{self._api_prefix}/transport-options/{transport_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message=(
                "Database API returned a malformed option delete response."
            ),
        )
        return envelope.data

    def _request_model(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        expected_statuses: set[int],
        response_type: Any,
        malformed_message: str,
    ) -> T:
        response = self._send(method, path, params=params, json=json)
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
                        "field": _DEPENDENCY_FIELD,
                        "issue": "response body did not match the expected schema",
                    },
                ],
            ) from exc

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            return self._client.request(method, path, params=params, json=json)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "Database API did not respond before the configured timeout.",
                [{"field": _DEPENDENCY_FIELD, "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            raise bad_gateway(
                "Database API returned an invalid HTTP response.",
                [
                    {
                        "field": _DEPENDENCY_FIELD,
                        "issue": "dependency returned invalid HTTP",
                    },
                ],
            ) from exc
        except httpx.NetworkError as exc:
            raise dependency_unavailable(
                "Database API is unavailable.",
                [{"field": _DEPENDENCY_FIELD, "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                "Database API request failed.",
                [
                    {
                        "field": _DEPENDENCY_FIELD,
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
                        "field": _DEPENDENCY_FIELD,
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
                            "field": _DEPENDENCY_FIELD,
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
                "Database API failed while processing the request.",
                [
                    {
                        "field": _DEPENDENCY_FIELD,
                        "issue": f"dependency returned HTTP {response.status_code}",
                    },
                ],
            )

        raise bad_gateway(
            "Database API returned an unexpected response.",
            [
                {
                    "field": _DEPENDENCY_FIELD,
                    "issue": f"unexpected HTTP {response.status_code}",
                },
            ],
        )
