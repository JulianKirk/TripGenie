from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings
from .models import CurrencyCode, Money, ProviderCost, ProviderCostItem


class ActivityCostItemResponse(BaseModel):
    item_id: str
    description: str
    status: str
    amount: Money
    currency: CurrencyCode


class ActivityCostResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    committed_cost_total: Money
    currency: CurrencyCode
    items: list[ActivityCostItemResponse] = Field(default_factory=list)


class ActivityApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._prefix = settings.activity_api_prefix
        self._client = httpx.Client(
            base_url=settings.activity_api_base_url,
            timeout=settings.activity_api_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def committed_cost(self, trip_id: str, currency: str) -> ProviderCost:
        try:
            response = self._client.get(
                f"{self._prefix}/trips/{trip_id}/committed-costs"
            )
        except httpx.TimeoutException:
            return ProviderCost(
                provider="activities",
                status="unavailable",
                detail="request timed out",
            )
        except httpx.RequestError:
            return ProviderCost(
                provider="activities", status="unavailable", detail="request failed"
            )
        if response.status_code != 200:
            return ProviderCost(
                provider="activities",
                status="unavailable",
                detail=f"HTTP {response.status_code}",
            )
        try:
            payload = ActivityCostResponse.model_validate(response.json())
        except (TypeError, ValueError, ValidationError):
            return ProviderCost(
                provider="activities",
                status="invalid_response",
                detail="response must include total and currency",
            )
        if payload.currency != currency:
            return ProviderCost(
                provider="activities",
                status="unavailable",
                currency=payload.currency,
                detail=f"cannot convert {payload.currency} to {currency}",
            )
        return ProviderCost(
            provider="activities",
            status="available",
            subtotal=payload.committed_cost_total,
            currency=payload.currency,
            items=[
                ProviderCostItem.model_validate(item.model_dump())
                for item in payload.items
            ],
        )
