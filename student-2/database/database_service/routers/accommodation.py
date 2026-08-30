"""Accommodation endpoints, plus the ORM-to-wire mapping they need.

The `_*_out` helpers live here rather than in a shared module because nothing
else uses them -- an accommodation is the only resource whose response shape
differs from its table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, status

from database_service.dependencies import SessionDep, get_or_404
from database_service.models import (
    Accommodation,
    City,
    Country,
    LocationDetails,
    RoomDetails,
)
from database_service.repository import (
    AccommodationRepository,
    CityRepository,
    CountryRepository,
)
from database_service.schemas import (
    AccommodationCreate,
    AccommodationCreated,
    AccommodationList,
    AccommodationOut,
    AccommodationQuery,
    AccommodationSummary,
    AccommodationUpdate,
    LocationDetailsIn,
    LocationDetailsOut,
    LocationSummary,
    RoomDetailsIn,
    RoomDetailsOut,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# The `:uuid` convertor is load-bearing, not decoration: without it
# "/accommodation/booking" matches "/accommodation/{id}" and the booking routes
# become unreachable unless they happen to be registered first. With it, the
# path only matches a well-formed UUID, so router mount order does not matter.
router = APIRouter(prefix="/accommodation", tags=["accommodation"])


def _location_out(accommodation: Accommodation) -> LocationDetailsOut:
    location = accommodation.location_details
    return LocationDetailsOut(
        country=location.country.name,
        city=location.city.name,
        street=location.street,
        street_number=location.street_number,
    )


def _accommodation_out(accommodation: Accommodation) -> AccommodationOut:
    return AccommodationOut(
        id=accommodation.id,
        name=accommodation.name,
        type=accommodation.type,
        description=accommodation.description,
        price_per_night=accommodation.price_per_night,
        availability_status=accommodation.availability_status,
        rating=accommodation.rating,
        amenities=list(accommodation.amenities),
        location_details=_location_out(accommodation),
        room_details=(
            RoomDetailsOut.model_validate(accommodation.room_details)
            if accommodation.room_details is not None
            else None
        ),
    )


def _accommodation_summary(accommodation: Accommodation) -> AccommodationSummary:
    location = accommodation.location_details
    return AccommodationSummary(
        id=accommodation.id,
        name=accommodation.name,
        type=accommodation.type,
        price_per_night=accommodation.price_per_night,
        availability_status=accommodation.availability_status,
        rating=accommodation.rating,
        location_details=LocationSummary(
            country=location.country.name, city=location.city.name
        ),
    )


def _resolve_location(session: Session, location: LocationDetailsIn) -> LocationDetails:
    """Look up the Country/City rows by name, creating either if it is new.

    The backend sends place names, not ids -- it has no way to know ours. Both
    lookups are get-or-create, which is what the API doc promises.
    """
    countries = CountryRepository(session)
    country = countries.get_by_name(location.country) or countries.add(
        Country(name=location.country)
    )
    cities = CityRepository(session)
    city = cities.get_by_name(location.city, country.id) or cities.add(
        City(name=location.city, country_id=country.id)
    )
    return LocationDetails(
        country_id=country.id,
        city_id=city.id,
        street=location.street,
        street_number=location.street_number,
    )


def _room_details(room: RoomDetailsIn) -> RoomDetails:
    return RoomDetails(
        room_count=room.room_count,
        bed_count=room.bed_count,
        bed_types=list(room.bed_types),
        description=room.description,
    )


@router.get("/{id:uuid}", response_model=AccommodationOut)
def get_accommodation(id: UUID, session: SessionDep) -> AccommodationOut:
    return _accommodation_out(
        get_or_404(AccommodationRepository(session), id, "accommodation")
    )


@router.api_route("", methods=["QUERY"], response_model=AccommodationList)
def query_accommodation(
    filters: AccommodationQuery, session: SessionDep
) -> AccommodationList:
    rows, total = AccommodationRepository(session).search(
        country=filters.country,
        city=filters.city,
        min_room_count=filters.min_room_count,
        limit=filters.limit,
        offset=filters.offset,
    )
    return AccommodationList(
        accommodations=[_accommodation_summary(row) for row in rows], total=total
    )


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=AccommodationCreated
)
def create_accommodation(
    payload: AccommodationCreate, session: SessionDep
) -> AccommodationCreated:
    accommodation = AccommodationRepository(session).add(
        Accommodation(
            name=payload.name,
            type=payload.type,
            description=payload.description,
            price_per_night=payload.price_per_night,
            availability_status=payload.availability_status,
            rating=payload.rating,
            amenities=list(payload.amenities),
            location_details=_resolve_location(session, payload.location_details),
            room_details=(
                _room_details(payload.room_details)
                if payload.room_details is not None
                else None
            ),
        )
    )
    return AccommodationCreated(id=accommodation.id, name=accommodation.name)


@router.put("/{id:uuid}", response_model=AccommodationOut)
def update_accommodation(
    id: UUID, payload: AccommodationUpdate, session: SessionDep
) -> AccommodationOut:
    accommodations = AccommodationRepository(session)
    accommodation = get_or_404(accommodations, id, "accommodation")
    fields = payload.model_dump(exclude_unset=True)
    location = fields.pop("location_details", None)
    room = fields.pop("room_details", None)
    for name, value in fields.items():
        setattr(accommodation, name, value)
    if location is not None:
        accommodation.location_details = _resolve_location(
            session, LocationDetailsIn(**location)
        )
    if room is not None:
        accommodation.room_details = _room_details(RoomDetailsIn(**room))
    # add() on an already-persistent instance is a no-op plus the commit.
    accommodations.add(accommodation)
    return _accommodation_out(accommodation)
