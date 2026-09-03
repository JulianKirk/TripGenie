from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .ai_recommendations import evaluate_search, plan_search
from .dependencies import AiDep, DbDep, ItineraryDep, LocationDep  # noqa: TC001
from .schemas import (
    RecommendationEvaluationRequest,
    RecommendationEvaluationResponse,
    RecommendationPlan,
    RecommendationPlanRequest,
    TripDirectory,
)

router = APIRouter(prefix="/activity/recommendations", tags=["recommendations"])

trip_router = APIRouter(prefix="/activity", tags=["recommendations"])


@trip_router.get("/trips", response_model=TripDirectory)
async def trips(itinerary: ItineraryDep) -> TripDirectory:
    try:
        found = await itinerary.list_itineraries()
    except HTTPException:
        return TripDirectory(available=False, trips=[])
    return TripDirectory(available=True, trips=found)


@router.post(
    "/plan", response_model=RecommendationPlan, response_model_exclude_none=True
)
async def plan(
    payload: RecommendationPlanRequest,
    request: Request,
    ai: AiDep,
    location: LocationDep,
    itinerary: ItineraryDep,
) -> RecommendationPlan:
    return await plan_search(
        payload,
        ai=ai,
        location=location,
        itinerary=itinerary,
        settings=request.app.state.settings,
    )


@router.post(
    "/evaluate",
    response_model=RecommendationEvaluationResponse,
    response_model_exclude_none=True,
)
async def evaluate(
    payload: RecommendationEvaluationRequest,
    request: Request,
    ai: AiDep,
    db: DbDep,
    location: LocationDep,
    itinerary: ItineraryDep,
) -> RecommendationEvaluationResponse:
    return await evaluate_search(
        payload,
        ai=ai,
        db=db,
        location=location,
        itinerary=itinerary,
        settings=request.app.state.settings,
    )
