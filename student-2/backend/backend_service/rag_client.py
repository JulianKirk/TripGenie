"""The shared host RAG server, as this service sees it.

Ported from Student 4's client. The RAG server owns retrieval, confidence and
citations; this service only asks it a question scoped to `student-2` (plus the
shared sources) and checks the answer is the documented shape.

Like `AI_MODE_URL`, an unset `RAG_URL` means there is no client at all and the
knowledge box says it is switched off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from backend_service.config import Settings

FEATURE = "student-2"
TOP_K = 5
UPSTREAM_MESSAGES = {
    "INDEX_NOT_READY": "The accommodation knowledge index is not ready.",
    "DEPENDENCY_UNAVAILABLE": "The accommodation knowledge service is unavailable.",
    "DEPENDENCY_TIMEOUT": "The accommodation knowledge service timed out.",
}

ConfidenceCategory = Literal["high", "medium", "low", "insufficient_context"]


class Citation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    path: str
    title: str
    section: str
    chunk_id: str
    excerpt: str


class Retrieval(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested_top_k: int = Field(ge=0)
    returned_chunks: int = Field(ge=0)
    maximum_score: float | None = None


class RagAnswer(BaseModel):
    """Shared RAG `/query` data, schema version 1."""

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["1"]
    run_id: str
    correlation_id: str
    answer: str
    confidence_category: ConfidenceCategory
    insufficient_context: bool
    citations: list[Citation]
    retrieval: Retrieval


class RagClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        # `transport` is the same test seam the other clients use.
        self._client = (
            httpx.AsyncClient(
                base_url=settings.rag_url,
                timeout=httpx.Timeout(settings.rag_timeout, connect=3.0),
                transport=transport,
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
                "The accommodation knowledge service is not configured.",
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
                "The accommodation knowledge service returned a malformed response.",
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
            "The accommodation knowledge service could not accept that question.",
        )
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "The accommodation knowledge service failed to answer.",
    )
