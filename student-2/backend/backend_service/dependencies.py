"""Shared route dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from backend_service.ai_client import AiClient
from backend_service.client import DatabaseClient
from backend_service.itinerary_client import ItineraryClient
from backend_service.location_client import LocationClient


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
