"""Shared route dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from backend_service.ai_client import AiClient
from backend_service.client import DatabaseClient
from backend_service.itinerary_client import ItineraryClient
from backend_service.location_client import LocationClient
from backend_service.multi_agent_client import MultiAgentClient
from backend_service.rag_client import RagClient


def get_db(request: Request) -> DatabaseClient:
    """The one client, built once in the app lifespan. It pools connections,
    so sharing it is the point -- do not build one per request."""
    return request.app.state.db


DbDep = Annotated[DatabaseClient, Depends(get_db)]


def get_itinerary(request: Request) -> ItineraryClient:
    """The one itinerary client, built once in the app lifespan -- same reason
    as `get_db`."""
    return request.app.state.itinerary


ItineraryDep = Annotated[ItineraryClient, Depends(get_itinerary)]


def get_location(request: Request) -> LocationClient:
    """The one location client, built once in the app lifespan -- same reason
    as `get_db`, and it carries the reference-data cache besides."""
    return request.app.state.location


LocationDep = Annotated[LocationClient, Depends(get_location)]


def get_ai(request: Request) -> AiClient:
    """The one AI-Mode client, built once in the app lifespan -- same reason as
    `get_db`. It exists even when the feature is switched off; it just says so."""
    return request.app.state.ai


AiDep = Annotated[AiClient, Depends(get_ai)]


def get_rag(request: Request) -> RagClient:
    """The one shared-RAG client, built once in the app lifespan. Like the
    AI-Mode one it exists even when switched off, and says so."""
    return request.app.state.rag


RagDep = Annotated[RagClient, Depends(get_rag)]


def get_multi_agent(request: Request) -> MultiAgentClient:
    """The one Multi-Agent Server client, built once in the app lifespan. It
    exists even when the feature is off; the routes check `enabled`."""
    return request.app.state.multi_agent


MultiAgentDep = Annotated[MultiAgentClient, Depends(get_multi_agent)]
