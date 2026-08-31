"""Shared route dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from backend_service.client import DatabaseClient
from backend_service.itinerary_client import ItineraryClient


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
