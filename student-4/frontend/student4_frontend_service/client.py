from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .errors import FrontendError
from .models import (
    ActivityDetail,
    ActivityPage,
    ActivityWrite,
    BackendHealth,
    CategoryList,
    DeleteResult,
    ItineraryPicker,
    ItinerarySelectionWrite,
    RecommendationEvaluation,
    RecommendationPlan,
    TripDirectory,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .config import Settings

ModelT = TypeVar("ModelT", bound=BaseModel)
UNAVAILABLE = "The activities service is unavailable. Please try again."
MALFORMED = "The activities service returned data that could not be displayed."
INVALID_REQUEST = "The activities service could not accept that request."


def _safe_client_detail(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if not isinstance(detail, list):
        return None

    messages: list[str] = []
    for item in detail[:3]:
        if not isinstance(item, dict) or not isinstance(item.get("msg"), str):
            continue
        location = item.get("loc")
        fields = (
            [str(part) for part in location if part not in {"body", "query", "path"}]
            if isinstance(location, list)
            else []
        )
        prefix = f"{'.'.join(fields)}: " if fields else ""
        messages.append(f"{prefix}{item['msg']}")
    return "; ".join(messages) or None


class BackendClient:
    """Typed HTTP adapter for the Student 4 backend and no other service."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=settings.backend_timeout,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> BackendHealth:
        return await self._request("GET", "/health", BackendHealth, {200})

    async def categories(self) -> CategoryList:
        return await self._request("GET", "/activity/categories", CategoryList, {200})

    async def search(self, body: dict[str, object]) -> ActivityPage:
        return await self._request("QUERY", "/activity", ActivityPage, {200}, json=body)

    async def activity(self, activity_id: UUID) -> ActivityDetail:
        return await self._request(
            "GET", f"/activity/{activity_id}", ActivityDetail, {200}
        )

    async def create_activity(self, body: ActivityWrite) -> ActivityDetail:
        return await self._request(
            "POST",
            "/activity",
            ActivityDetail,
            {201},
            json=body.model_dump(mode="json", exclude_none=True),
        )

    async def replace_activity(
        self,
        activity_id: UUID,
        body: ActivityWrite,
    ) -> ActivityDetail:
        return await self._request(
            "PUT",
            f"/activity/{activity_id}",
            ActivityDetail,
            {200},
            json=body.model_dump(mode="json", exclude_none=True),
        )

    async def delete_activity(self, activity_id: UUID) -> DeleteResult:
        return await self._request(
            "DELETE", f"/activity/{activity_id}", DeleteResult, {200}
        )

    async def itineraries(self, activity_id: UUID) -> ItineraryPicker:
        return await self._request(
            "GET", f"/activity/{activity_id}/itineraries", ItineraryPicker, {200}
        )

    async def put_itinerary(
        self,
        activity_id: UUID,
        trip_id: str,
        body: ItinerarySelectionWrite,
    ) -> ItineraryPicker:
        return await self._request(
            "PUT",
            f"/activity/{activity_id}/itineraries/{trip_id}",
            ItineraryPicker,
            {200},
            json=body.model_dump(mode="json", exclude_none=True),
        )

    async def delete_itinerary(
        self,
        activity_id: UUID,
        trip_id: str,
    ) -> ItineraryPicker:
        return await self._request(
            "DELETE",
            f"/activity/{activity_id}/itineraries/{trip_id}",
            ItineraryPicker,
            {200},
        )

    async def trips(self) -> TripDirectory:
        return await self._request("GET", "/activity/trips", TripDirectory, {200})

    async def plan_recommendations(self, body: dict[str, object]) -> RecommendationPlan:
        return await self._request(
            "POST",
            "/activity/recommendations/plan",
            RecommendationPlan,
            {200},
            json=body,
            request_timeout=self._settings.ai_timeout,
        )

    async def evaluate_recommendations(
        self, body: dict[str, object]
    ) -> RecommendationEvaluation:
        return await self._request(
            "POST",
            "/activity/recommendations/evaluate",
            RecommendationEvaluation,
            {200},
            json=body,
            request_timeout=self._settings.ai_timeout,
        )

    async def _request(
        self,
        method: str,
        path: str,
        response_type: type[ModelT],
        expected_statuses: set[int],
        *,
        json: dict[str, object] | None = None,
        request_timeout: float | None = None,
    ) -> ModelT:
        try:
            response = (
                await self._client.request(method, path, json=json)
                if request_timeout is None
                else await self._client.request(
                    method, path, json=json, timeout=request_timeout
                )
            )
        except httpx.RequestError as exc:
            raise FrontendError(
                kind="unavailable", status_code=503, detail=UNAVAILABLE
            ) from exc

        if response.status_code not in expected_statuses:
            detail = UNAVAILABLE
            try:
                payload: object = response.json()
            except ValueError:
                payload = None
            if 400 <= response.status_code < 500:
                detail = _safe_client_detail(payload) or INVALID_REQUEST
            raise FrontendError(
                kind="backend_error",
                status_code=response.status_code,
                detail=detail,
            )

        try:
            return response_type.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise FrontendError(
                kind="malformed_upstream", status_code=502, detail=MALFORMED
            ) from exc
