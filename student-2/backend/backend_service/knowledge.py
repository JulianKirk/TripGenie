"""The knowledge box: a question answered from the shared RAG server.

Every outcome is a 200 with a `status`, so the page has one shape to draw:
an answer with citations, an honest "not enough context", or why it could not
ask. Ported from Student 4's `knowledge.ask`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend_service.rag_client import (
    Citation,
    ConfidenceCategory,
    Retrieval,
)

if TYPE_CHECKING:
    from backend_service.rag_client import RagClient


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=500)


class KnowledgeResponse(BaseModel):
    status: Literal["answered", "insufficient_context", "disabled", "error"]
    request_id: str
    answer: str | None = None
    confidence_category: ConfidenceCategory | None = None
    citations: list[Citation] = Field(default_factory=list)
    retrieval: Retrieval | None = None
    run_id: str | None = None
    error: str | None = None


async def ask(question: str, rag: RagClient) -> KnowledgeResponse:
    request_id = f"student2-rag-{uuid4().hex[:16]}"
    if not rag.configured:
        return KnowledgeResponse(
            status="disabled",
            request_id=request_id,
            error=(
                "The accommodation guide (RAG) is switched off here. "
                "Search and everything else on the page still work."
            ),
        )
    try:
        result = await rag.query(question, request_id)
    except HTTPException as exc:
        return KnowledgeResponse(
            status="error", request_id=request_id, error=str(exc.detail)
        )
    # Grounded answers always carry citations; none is the server abstaining.
    if result.insufficient_context or not result.citations:
        return KnowledgeResponse(
            status="insufficient_context",
            request_id=request_id,
            answer=result.answer,
            confidence_category="insufficient_context",
            retrieval=result.retrieval,
            run_id=result.run_id,
        )
    return KnowledgeResponse(
        status="answered",
        request_id=request_id,
        answer=result.answer,
        confidence_category=result.confidence_category,
        citations=result.citations,
        retrieval=result.retrieval,
        run_id=result.run_id,
    )
