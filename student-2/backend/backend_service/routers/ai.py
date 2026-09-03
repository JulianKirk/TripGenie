"""The ask box: a question in English, answered with real accommodations.

Two steps, and the second one is not new. `ai_search` gets filters -- and a
sentence answering the question in words -- out of the shared AI-Mode service;
`accommodation.search` runs them, exactly as it runs the filters a person typed.
The model chooses *what to look for* and never *what comes back*.

POST rather than QUERY, unlike the search it delegates to: this one calls a
model and may retry, so it is neither safe nor idempotent, and HTMX cannot issue
QUERY from a page anyway.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend_service import ai_search
from backend_service.dependencies import (  # noqa: TC001  (runtime)
    AiDep,
    DbDep,
    LocationDep,
)
from backend_service.routers.accommodation import search
from backend_service.schemas import (
    AccommodationQueryRequest,
    AiSearchRequest,
    AiSearchResponse,
)

router = APIRouter(prefix="/accommodation", tags=["accommodation"])


@router.post(
    "/ai-search", response_model=AiSearchResponse, response_model_exclude_none=True
)
async def ai_accommodation_search(
    body: AiSearchRequest,
    request: Request,
    ai: AiDep,
    db: DbDep,
    location: LocationDep,
) -> AiSearchResponse:
    settings = request.app.state.settings
    answer = await ai_search.filters_for(body.query, ai, location, settings)
    # The caller's paging wins. The model has no idea how big the page on the
    # other end is, and the prompt tells it not to try.
    query = AccommodationQueryRequest.model_validate(
        answer.model_dump(exclude={"reply"})
        | {"limit": body.limit, "offset": body.offset}
    )
    found = await search(query, db, location)
    return AiSearchResponse(
        query_used=query,
        reply=answer.reply,
        accommodations=found.accommodations,
        total=found.total,
    )
