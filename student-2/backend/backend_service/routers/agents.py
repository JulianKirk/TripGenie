"""Accommodation planning by the shared Planner -> Worker -> Reviewer agents.

Three steps, and the server never writes Student 2 data. `POST /agent-runs`
starts a run and returns at once, still planning; `GET` is what the page polls;
`POST .../review` records the human decision and, only then, pins what was
approved to the run's trip -- through the same itinerary client the stay panel
uses, so student 1's rules apply. Nothing is added to a trip without a person
saying so, and nothing the tools did not return can be added at all.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from backend_service import agent_runs
from backend_service.agent_schemas import (
    AgentReviewRequest,
    AgentRunRequest,
    AgentRunView,
    AgentSavedStay,
    AgentSaveError,
)
from backend_service.dependencies import (  # noqa: TC001  (runtime)
    DbDep,
    ItineraryDep,
    LocationDep,
    MultiAgentDep,
)
from backend_service.routers.accommodation import get_accommodation

if TYPE_CHECKING:
    from backend_service.multi_agent_client import MultiAgentClient
    from backend_service.schemas import Accommodation

LOGGER = logging.getLogger(__name__)
DISABLED = "MULTI_AGENT_DISABLED: the Multi-Agent Server is switched off here."
UNKNOWN_TRIP = "unknown trip"
RUN_ID = re.compile(r"magent_[0-9a-f]{12}")

router = APIRouter(prefix="/accommodation/agent-runs", tags=["agents"])


def _client(agents: MultiAgentClient) -> MultiAgentClient:
    if not agents.enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DISABLED)
    return agents


def _lookup(db: DbDep, location: LocationDep):  # type: ignore[no-untyped-def]
    async def lookup(listing_id: str) -> Accommodation | None:
        try:
            return await get_accommodation(UUID(listing_id), db, location)
        except (HTTPException, ValueError):
            return None  # gone since the run, or not a listing

    return lookup


def _run_id(run_id: str) -> str:
    """Refuse anything that is not a run id before it reaches the server's URL."""
    if RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RUN_NOT_FOUND: unknown run")
    return run_id


@router.post(
    "",
    response_model=AgentRunView,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_agent_run(
    body: AgentRunRequest,
    request: Request,
    agents: MultiAgentDep,
    db: DbDep,
    location: LocationDep,
    itinerary: ItineraryDep,
) -> AgentRunView:
    client = _client(agents)
    if body.trip_id is not None:
        trips = await itinerary.list_itineraries()
        if body.trip_id not in {record.get("id") for record in trips}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, UNKNOWN_TRIP)
    request_body = agent_runs.build_run_request(
        request.app.state.settings,
        body,
        await location.countries(),
        await location.cities(),
    )
    run = await client.start_run(request_body)
    LOGGER.info(
        "agent_run_started correlation_id=%s run_id=%s",
        request_body["correlation_id"],
        run.get("run_id"),
    )
    return await agent_runs.to_view(run, _lookup(db, location))


@router.get("/{run_id}", response_model=AgentRunView, response_model_exclude_none=True)
async def get_agent_run(
    run_id: str, agents: MultiAgentDep, db: DbDep, location: LocationDep
) -> AgentRunView:
    run = await _client(agents).get_run(_run_id(run_id))
    return await agent_runs.to_view(run, _lookup(db, location))


@router.post(
    "/{run_id}/review",
    response_model=AgentRunView,
    response_model_exclude_none=True,
)
async def review_agent_run(
    run_id: str,
    decision: AgentReviewRequest,
    agents: MultiAgentDep,
    db: DbDep,
    location: LocationDep,
    itinerary: ItineraryDep,
) -> AgentRunView:
    """Record the human decision, then pin what was approved to the trip.

    Only grounded ids are pinned, and one failure does not undo the others or
    the decision itself.
    """
    client = _client(agents)
    run_id = _run_id(run_id)
    run = await client.get_run(run_id)
    decided = await client.review(run_id, agent_runs.review_body(run, decision))

    saved: list[AgentSavedStay] = []
    errors: list[AgentSaveError] = []
    trip_id = decided.get("trip_id")
    if trip_id:
        grounded = agent_runs.grounded_ids(decided)
        for listing_id in agent_runs.approved_ids(decided):
            if listing_id.lower() not in grounded:
                errors.append(
                    AgentSaveError(
                        accommodation_id=listing_id,
                        code="UNGROUNDED_SUGGESTION",
                        message="No accommodation tool returned this id, so it "
                        "was not added.",
                    )
                )
                continue
            try:
                await itinerary.add(
                    UUID(listing_id), trip_id, decision.check_in, decision.check_out
                )
            except (HTTPException, ValueError) as exc:
                errors.append(
                    AgentSaveError(
                        accommodation_id=listing_id,
                        code=f"HTTP_{getattr(exc, 'status_code', 400)}",
                        message=str(getattr(exc, "detail", exc)),
                    )
                )
                continue
            saved.append(
                AgentSavedStay(
                    accommodation_id=listing_id,
                    trip_id=trip_id,
                    check_in=decision.check_in,
                    check_out=decision.check_out,
                )
            )
    LOGGER.info(
        "agent_run_decided run_id=%s decision=%s saved=%s save_errors=%s",
        run_id,
        decision.decision,
        len(saved),
        len(errors),
    )
    view = await agent_runs.to_view(decided, _lookup(db, location))
    return view.model_copy(update={"saved": saved, "save_errors": errors})
