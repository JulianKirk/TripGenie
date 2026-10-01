from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError

from .knowledge_models import RagAnswer

if TYPE_CHECKING:
    from .config import Settings

FEATURE = "student-4"
TOP_K = 5
UPSTREAM_MESSAGES = {
    "INDEX_NOT_READY": "The activity knowledge index is not ready.",
    "DEPENDENCY_UNAVAILABLE": "The activity knowledge service is unavailable.",
    "DEPENDENCY_TIMEOUT": "The activity knowledge service timed out.",
}


class RagClient:
    """HTTP adapter for the shared host RAG server, scoped to Student 4."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = (
            httpx.AsyncClient(
                base_url=settings.rag_url,
                timeout=httpx.Timeout(settings.rag_timeout, connect=3.0),
                transport=transport,
                follow_redirects=False,
            )
            if settings.rag_url
            else None
        )

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def query(self, question: str, correlation_id: str) -> RagAnswer:
        if self._client is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "The activity knowledge service is not configured.",
            )
        try:
            response = await self._client.post(
                "/query",
                json={
                    "query": question,
                    "feature": FEATURE,
                    "top_k": TOP_K,
                    "correlation_id": correlation_id,
                },
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status.HTTP_504_GATEWAY_TIMEOUT,
                UPSTREAM_MESSAGES["DEPENDENCY_TIMEOUT"],
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                UPSTREAM_MESSAGES["DEPENDENCY_UNAVAILABLE"],
            ) from exc

        if response.is_error:
            raise _upstream_error(response)
        try:
            return RagAnswer.model_validate(response.json()["data"])
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "The activity knowledge service returned a malformed response.",
            ) from exc


def _upstream_error(response: httpx.Response) -> HTTPException:
    try:
        code = str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        code = ""
    if response.status_code in {503, 504} and code in UPSTREAM_MESSAGES:
        return HTTPException(response.status_code, UPSTREAM_MESSAGES[code])
    if code == "VALIDATION_ERROR":
        return HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The activity knowledge service could not accept that question.",
        )
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "The activity knowledge service failed to answer.",
    )
