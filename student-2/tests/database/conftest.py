"""Shared fixtures for the accommodation database service tests.

`database_service` is importable because student-2 is pip-installed (see
student-2/pyproject.toml) -- no PYTHONPATH needed.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database_service.models import (
    Accommodation,
    AccommodationType,
    AvailabilityStatus,
    Base,
    BedType,
    City,
    Country,
    LocationDetails,
    RoomDetails,
    User,
)
from database_service.repository import (
    AccommodationBookingRepository,
    AccommodationRepository,
    AccommodationUserRatingRepository,
)


@pytest.fixture
def session():
    """Fresh in-memory SQLite DB per test -- no dependency on database.py."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def accommodations(session):
    return AccommodationRepository(session)


@pytest.fixture
def bookings(session):
    return AccommodationBookingRepository(session)


@pytest.fixture
def ratings(session):
    return AccommodationUserRatingRepository(session)


@pytest.fixture
def user(session):
    user = User(id=uuid4(), name="Mark", email="mark@example.com")
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def australia(session):
    country = Country(id=uuid4(), name="Australia")
    session.add(country)
    session.commit()
    return country


@pytest.fixture
def katoomba(session, australia):
    city = City(id=uuid4(), name="Katoomba", country_id=australia.id)
    session.add(city)
    session.commit()
    return city


@pytest.fixture
def sydney(session, australia):
    city = City(id=uuid4(), name="Sydney", country_id=australia.id)
    session.add(city)
    session.commit()
    return city


@pytest.fixture
def camping(accommodations, australia, katoomba):
    return accommodations.add(
        Accommodation(
            id=uuid4(),
            name="Cosy Cabin",
            type=AccommodationType.CAMPING,
            description="tent site",
            price_per_night=Decimal("20.00"),
            availability_status=AvailabilityStatus.AVAILABLE,
            location_details=LocationDetails(
                country_id=australia.id,
                city_id=katoomba.id,
                street="Cliff Dr",
                street_number=1,
            ),
            room_details=RoomDetails(
                room_count=1, bed_count=1, bed_types=[BedType.SINGLE]
            ),
        )
    )


@pytest.fixture
def hotel(accommodations, australia, sydney):
    return accommodations.add(
        Accommodation(
            id=uuid4(),
            name="Grand Hotel",
            type=AccommodationType.HOTEL,
            description="city hotel",
            price_per_night=Decimal("250.00"),
            availability_status=AvailabilityStatus.AVAILABLE,
            location_details=LocationDetails(
                country_id=australia.id,
                city_id=sydney.id,
                street="George St",
                street_number=1,
            ),
            room_details=RoomDetails(
                room_count=40, bed_count=60, bed_types=[BedType.QUEEN, BedType.KING]
            ),
        )
    )
