from typing import Annotated, cast

from fastapi import Depends, Request

from .client import DatabaseClient
from .itinerary_client import ItineraryClient
from .location_client import LocationClient


def get_db(request: Request) -> DatabaseClient:
    return cast("DatabaseClient", request.app.state.db)


def get_location(request: Request) -> LocationClient:
    return cast("LocationClient", request.app.state.location)


def get_itinerary(request: Request) -> ItineraryClient:
    return cast("ItineraryClient", request.app.state.itinerary)


DbDep = Annotated[DatabaseClient, Depends(get_db)]
LocationDep = Annotated[LocationClient, Depends(get_location)]
ItineraryDep = Annotated[ItineraryClient, Depends(get_itinerary)]
