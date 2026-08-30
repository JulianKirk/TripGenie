"""HTTP wrapper around the accommodation database.

Internal-only: the backend service is the sole caller, so there is no auth and
no rate limiting here. See ../../docs/database-service-api.md for the contract.
"""

from __future__ import annotations

# Iterator and UUID are imported at runtime, not under TYPE_CHECKING: FastAPI
# evaluates route and dependency annotations when it builds the app.
from collections.abc import AsyncIterator, Iterator  # noqa: TC003
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from database_service import errors
from database_service.config import Settings
from database_service.database import create_engine_and_session
from database_service.models import (
    Accommodation,
    AccommodationBooking,
    AccommodationUserRating,
    City,
    Country,
    LocationDetails,
    RoomDetails,
)
from database_service.repository import (
    AccommodationBookingRepository,
    AccommodationRepository,
    AccommodationUserRatingRepository,
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
    BookingCreate,
    BookingCreated,
    BookingList,
    BookingOut,
    Health,
    LocationDetailsIn,
    LocationDetailsOut,
    LocationSummary,
    RatingCreate,
    RatingCreated,
    RatingList,
    RatingOut,
    RoomDetailsIn,
    RoomDetailsOut,
)

NOT_FOUND = "not found"


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, always closed. Tests override this to point at
    their own engine."""
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


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


def _get_or_404(repository, id: UUID, what: str):
    row = repository.get(id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} {NOT_FOUND}")
    return row


router = APIRouter()


@router.get("/health", response_model=Health)
def health(request: Request) -> Health:
    # ponytail: connect-and-close, no SELECT. Proves the database file
    # opens; does not prove the schema is there. That is fine because the
    # lifespan runs create_all -- a missing schema means no startup at all.
    # Swap in a real query if health ever has to mean "usable".
    with request.app.state.engine.connect():
        pass
    return Health(status="ok", service=request.app.state.settings.service_name)


# Bookings and ratings are registered before /accommodation/{id}: routes
# match in registration order, so "/accommodation/booking" would otherwise
# be read as an accommodation whose id is "booking".

# --- bookings -------------------------------------------------------


@router.get("/accommodation/booking", response_model=BookingList)
def list_bookings(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookingList:
    rows, total = AccommodationBookingRepository(session).list(limit, offset)
    return BookingList(bookings=rows, total=total)


@router.get("/accommodation/booking/{id}", response_model=BookingOut)
def get_booking(id: UUID, session: SessionDep) -> AccommodationBooking:
    return _get_or_404(AccommodationBookingRepository(session), id, "booking")


@router.post(
    "/accommodation/booking",
    status_code=status.HTTP_201_CREATED,
    response_model=BookingCreated,
)
def create_booking(payload: BookingCreate, session: SessionDep) -> AccommodationBooking:
    _get_or_404(
        AccommodationRepository(session), payload.accommodation_id, "accommodation"
    )
    return AccommodationBookingRepository(session).add(
        AccommodationBooking(**payload.model_dump())
    )


@router.delete("/accommodation/booking/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(id: UUID, session: SessionDep) -> None:
    bookings = AccommodationBookingRepository(session)
    _get_or_404(bookings, id, "booking")
    bookings.delete(id)


# --- ratings --------------------------------------------------------


@router.get("/accommodation/rating", response_model=RatingList)
def list_ratings(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RatingList:
    rows, total = AccommodationUserRatingRepository(session).list(limit, offset)
    return RatingList(ratings=rows, total=total)


@router.get("/accommodation/rating/{id}", response_model=RatingOut)
def get_rating(id: UUID, session: SessionDep) -> AccommodationUserRating:
    return _get_or_404(AccommodationUserRatingRepository(session), id, "rating")


@router.post(
    "/accommodation/rating",
    status_code=status.HTTP_201_CREATED,
    response_model=RatingCreated,
)
def create_rating(
    payload: RatingCreate, session: SessionDep
) -> AccommodationUserRating:
    _get_or_404(
        AccommodationRepository(session), payload.accommodation_id, "accommodation"
    )
    # ponytail: Accommodation.rating is not recomputed here. The API doc
    # treats it as a field the caller sets, not a derived average. Add the
    # rollup when something actually asks for an aggregate.
    return AccommodationUserRatingRepository(session).add(
        AccommodationUserRating(**payload.model_dump())
    )


@router.delete("/accommodation/rating/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rating(id: UUID, session: SessionDep) -> None:
    ratings = AccommodationUserRatingRepository(session)
    _get_or_404(ratings, id, "rating")
    ratings.delete(id)


# --- accommodations -------------------------------------------------


@router.get("/accommodation/{id}", response_model=AccommodationOut)
def get_accommodation(id: UUID, session: SessionDep) -> AccommodationOut:
    return _accommodation_out(
        _get_or_404(AccommodationRepository(session), id, "accommodation")
    )


@router.api_route("/accommodation", methods=["QUERY"], response_model=AccommodationList)
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
    "/accommodation",
    status_code=status.HTTP_201_CREATED,
    response_model=AccommodationCreated,
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


@router.put("/accommodation/{id}", response_model=AccommodationOut)
def update_accommodation(
    id: UUID, payload: AccommodationUpdate, session: SessionDep
) -> AccommodationOut:
    accommodations = AccommodationRepository(session)
    accommodation = _get_or_404(accommodations, id, "accommodation")
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, session_factory = create_engine_and_session(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        yield
        engine.dispose()

    app = FastAPI(title="Accommodation Database Service", lifespan=lifespan)
    errors.register(app)
    app.include_router(router)
    return app


app = create_app()
