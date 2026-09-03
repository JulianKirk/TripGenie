from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import (
    DatabaseHealthPayload,
    DataEnvelope,
    DeleteResponse,
    ErrorEnvelope,
    ItineraryCategory,
    ItineraryItemCreate,
    ItineraryItemRecord,
    ItineraryItemUpdate,
    TripAccommodationRecord,
    TripActivityRecord,
    TripCreate,
    TripRecord,
    TripStatus,
    TripUpdate,
)

T = TypeVar("T")

HANDLED_ERROR_STATUSES = {400, 404, 409, 422, 503}


class DatabaseApiClient:
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

    def list_trips(
        self,
        *,
        status: TripStatus | None = None,
        destination: str | None = None,
    ) -> list[TripRecord]:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status.value
        if destination is not None:
            params["destination"] = destination

        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/trips",
            params=params or None,
            expected_statuses={200},
            response_type=DataEnvelope[list[TripRecord]],
            malformed_message="Database API returned a malformed trip list response.",
        )
        return envelope.data

    def create_trip(self, payload: TripCreate) -> TripRecord:
        envelope = self._request_model(
            "POST",
            f"{self._api_prefix}/trips",
            json=payload.model_dump(mode="json", exclude_none=True),
            expected_statuses={201},
            response_type=DataEnvelope[TripRecord],
            malformed_message="Database API returned a malformed trip create response.",
        )
        return envelope.data

    def get_trip(self, trip_id: str) -> TripRecord:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}",
            expected_statuses={200},
            response_type=DataEnvelope[TripRecord],
            malformed_message="Database API returned a malformed trip response.",
        )
        return envelope.data

    def update_trip(self, trip_id: str, payload: TripUpdate) -> TripRecord:
        envelope = self._request_model(
            "PATCH",
            f"{self._api_prefix}/trips/{trip_id}",
            json=payload.model_dump(mode="json", exclude_unset=True),
            expected_statuses={200},
            response_type=DataEnvelope[TripRecord],
            malformed_message="Database API returned a malformed trip update response.",
        )
        return envelope.data

    def delete_trip(self, trip_id: str) -> DeleteResponse:
        envelope = self._request_model(
            "DELETE",
            f"{self._api_prefix}/trips/{trip_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message="Database API returned a malformed trip delete response.",
        )
        return envelope.data

    def list_itinerary_items(
        self,
        trip_id: str,
        *,
        date: str | None = None,
        category: ItineraryCategory | None = None,
    ) -> list[ItineraryItemRecord]:
        params: dict[str, str] = {}
        if date is not None:
            params["date"] = date
        if category is not None:
            params["category"] = category.value

        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}/itinerary-items",
            params=params or None,
            expected_statuses={200},
            response_type=DataEnvelope[list[ItineraryItemRecord]],
            malformed_message=(
                "Database API returned a malformed itinerary list response."
            ),
        )
        return envelope.data

    def create_itinerary_item(
        self,
        trip_id: str,
        payload: ItineraryItemCreate,
    ) -> ItineraryItemRecord:
        envelope = self._request_model(
            "POST",
            f"{self._api_prefix}/trips/{trip_id}/itinerary-items",
            json=payload.model_dump(mode="json", exclude_none=True),
            expected_statuses={201},
            response_type=DataEnvelope[ItineraryItemRecord],
            malformed_message=(
                "Database API returned a malformed itinerary create response."
            ),
        )
        return envelope.data

    def get_itinerary_item(self, item_id: str) -> ItineraryItemRecord:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/itinerary-items/{item_id}",
            expected_statuses={200},
            response_type=DataEnvelope[ItineraryItemRecord],
            malformed_message="Database API returned a malformed itinerary response.",
        )
        return envelope.data

    def update_itinerary_item(
        self,
        item_id: str,
        payload: ItineraryItemUpdate,
    ) -> ItineraryItemRecord:
        envelope = self._request_model(
            "PATCH",
            f"{self._api_prefix}/itinerary-items/{item_id}",
            json=payload.model_dump(mode="json", exclude_unset=True),
            expected_statuses={200},
            response_type=DataEnvelope[ItineraryItemRecord],
            malformed_message=(
                "Database API returned a malformed itinerary update response."
            ),
        )
        return envelope.data

    def delete_itinerary_item(self, item_id: str) -> DeleteResponse:
        envelope = self._request_model(
            "DELETE",
            f"{self._api_prefix}/itinerary-items/{item_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message=(
                "Database API returned a malformed itinerary delete response."
            ),
        )
        return envelope.data

    def list_trip_accommodations(self, trip_id: str) -> list[TripAccommodationRecord]:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}/accommodations",
            expected_statuses={200},
            response_type=DataEnvelope[list[TripAccommodationRecord]],
            malformed_message=(
                "Database API returned a malformed trip accommodation list response."
            ),
        )
        return envelope.data

    def add_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
        date: str,
        check_out: str | None = None,
        check_in_time: str | None = None,
        check_out_time: str | None = None,
    ) -> TripAccommodationRecord:
        envelope = self._request_model(
            "PUT",
            f"{self._api_prefix}/trips/{trip_id}/accommodations/{accommodation_id}",
            json={
                "date": date,
                "check_in_time": check_in_time,
                "check_out": check_out,
                "check_out_time": check_out_time,
            },
            expected_statuses={200},
            response_type=DataEnvelope[TripAccommodationRecord],
            malformed_message=(
                "Database API returned a malformed trip accommodation response."
            ),
        )
        return envelope.data

    def remove_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
    ) -> DeleteResponse:
        envelope = self._request_model(
            "DELETE",
            f"{self._api_prefix}/trips/{trip_id}/accommodations/{accommodation_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message=(
                "Database API returned a malformed trip accommodation delete response."
            ),
        )
        return envelope.data

    def list_trips_for_accommodation(
        self,
        accommodation_id: str,
    ) -> list[TripRecord]:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/accommodations/{accommodation_id}/trips",
            expected_statuses={200},
            response_type=DataEnvelope[list[TripRecord]],
            malformed_message=(
                "Database API returned a malformed accommodation trip list response."
            ),
        )
        return envelope.data

    def list_trip_activities(self, trip_id: str) -> list[TripActivityRecord]:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/trips/{trip_id}/activities",
            expected_statuses={200},
            response_type=DataEnvelope[list[TripActivityRecord]],
            malformed_message=(
                "Database API returned a malformed trip activity list response."
            ),
        )
        return envelope.data

    def add_trip_activity(
        self,
        trip_id: str,
        activity_id: str,
        date: str,
        start_time: str | None = None,
    ) -> TripActivityRecord:
        envelope = self._request_model(
            "PUT",
            f"{self._api_prefix}/trips/{trip_id}/activities/{activity_id}",
            json={"date": date, "start_time": start_time},
            expected_statuses={200},
            response_type=DataEnvelope[TripActivityRecord],
            malformed_message=(
                "Database API returned a malformed trip activity response."
            ),
        )
        return envelope.data

    def remove_trip_activity(self, trip_id: str, activity_id: str) -> DeleteResponse:
        envelope = self._request_model(
            "DELETE",
            f"{self._api_prefix}/trips/{trip_id}/activities/{activity_id}",
            expected_statuses={200},
            response_type=DataEnvelope[DeleteResponse],
            malformed_message=(
                "Database API returned a malformed trip activity delete response."
            ),
        )
        return envelope.data

    def list_trips_for_activity(self, activity_id: str) -> list[TripRecord]:
        envelope = self._request_model(
            "GET",
            f"{self._api_prefix}/activities/{activity_id}/trips",
            expected_statuses={200},
            response_type=DataEnvelope[list[TripRecord]],
            malformed_message=(
                "Database API returned a malformed activity trip list response."
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
                        "field": "database",
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
                [{"field": "database", "issue": "request timed out"}],
            ) from exc
        except httpx.ProtocolError as exc:
            raise bad_gateway(
                "Database API returned an invalid HTTP response.",
                [{"field": "database", "issue": "dependency returned invalid HTTP"}],
            ) from exc
        except httpx.NetworkError as exc:
            raise dependency_unavailable(
                "Database API is unavailable.",
                [{"field": "database", "issue": "connection failed"}],
            ) from exc
        except httpx.RequestError:
            raise dependency_unavailable(
                "Database API request failed.",
                [{"field": "database", "issue": "request could not be completed"}],
            ) from None

    @staticmethod
    def _decode_json(response: httpx.Response, message: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise bad_gateway(
                message,
                [{"field": "database", "issue": "response body was not valid JSON"}],
            ) from exc

    def _raise_error_response(self, response: httpx.Response) -> None:
        if response.status_code in HANDLED_ERROR_STATUSES:
            payload = self._decode_json(
                response,
                "Database API returned a malformed error response.",
            )
            try:
                envelope = ErrorEnvelope.model_validate(payload)
            except ValidationError as exc:
                raise bad_gateway(
                    "Database API returned a malformed error response.",
                    [
                        {
                            "field": "database",
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
                        "field": "database",
                        "issue": f"dependency returned HTTP {response.status_code}",
                    },
                ],
            )

        raise bad_gateway(
            "Database API returned an unexpected response.",
            [
                {
                    "field": "database",
                    "issue": f"unexpected HTTP {response.status_code}",
                },
            ],
        )
