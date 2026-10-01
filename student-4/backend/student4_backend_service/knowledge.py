"""Ask the shared RAG server for grounded activity knowledge and map the result."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import HTTPException

from .knowledge_models import KnowledgeResponse

if TYPE_CHECKING:
    from .config import Settings
    from .knowledge_models import KnowledgeRequest
    from .rag_client import RagClient


async def ask(
    payload: KnowledgeRequest, settings: Settings, rag: RagClient
) -> KnowledgeResponse:
    request_id = f"student4-rag-{uuid4().hex[:16]}"
    if not settings.rag_enabled:
        return KnowledgeResponse(
            status="disabled",
            request_id=request_id,
            error=(
                "The activity knowledge assistant (RAG) is disabled in this "
                "environment. Ordinary activity browsing is still available."
            ),
        )
    try:
        result = await rag.query(payload.question, request_id)
    except HTTPException as exc:
        return KnowledgeResponse(
            status="error", request_id=request_id, error=str(exc.detail)
        )
    # The RAG server guarantees grounded answers carry citations; an empty list
    # is its abstention signal, so treat it as insufficient context too.
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
