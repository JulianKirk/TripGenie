from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import Settings
from .models import CurrencyCode, Money, ProviderCost


class TransportCostResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    estimated_cost_total: Money
    currency: CurrencyCode


class TransportApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._prefix = settings.transport_api_prefix
        self._client = httpx.Client(
            base_url=settings.transport_api_base_url,
            timeout=settings.transport_api_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def committed_cost(self, trip_id: str, currency: str) -> ProviderCost:
        try:
            response = self._client.get(f"{self._prefix}/trips/{trip_id}/transport")
        except httpx.TimeoutException:
            return ProviderCost(
                provider="transport", status="unavailable", detail="request timed out"
            )
        except httpx.RequestError:
            return ProviderCost(
                provider="transport", status="unavailable", detail="request failed"
            )
        if response.status_code != 200:
            return ProviderCost(
                provider="transport",
                status="unavailable",
                detail=f"HTTP {response.status_code}",
            )
        try:
            payload = TransportCostResponse.model_validate(response.json()["data"])
        except (KeyError, TypeError, ValueError, ValidationError):
            return ProviderCost(
                provider="transport",
                status="invalid_response",
                detail="response must include total and currency",
            )
        if payload.currency != currency:
            return ProviderCost(
                provider="transport",
                status="unavailable",
                currency=payload.currency,
                detail=f"cannot convert {payload.currency} to {currency}",
            )
        return ProviderCost(
            provider="transport",
            status="available",
            subtotal=payload.estimated_cost_total,
            currency=payload.currency,
        )
