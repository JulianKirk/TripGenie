from __future__ import annotations

from typing import Any

import httpx


async def generate_with_ai_mode(
    *,
    base_url: str,
    prompt: str,
    schema: dict[str, Any] | None = None,
    model: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, str] | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "metadata": metadata or {},
    }
    if schema is not None:
        payload["schema"] = schema
    if model is not None:
        payload["model"] = model
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id

    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout_seconds,
        follow_redirects=False,
    ) as client:
        response = await client.post("/generate", json=payload)
        response.raise_for_status()
        return response.json()["data"]
