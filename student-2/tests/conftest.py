"""Shared fixtures for the accommodation microservice tests.

Import paths (repo root for `shared`, student-2 for `database`) come from
`pythonpath` in the repo-root pytest.ini -- no PYTHONPATH needed.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import (
    Accommodation,
    AccommodationType,
    AvailabilityStatus,
    BedType,
    RoomDetails,
)
from database.repository import (
    AccommodationBookingRepository,
    AccommodationRatingRepository,
    AccommodationRepository,
)
from shared.backend.models import Base, User


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
    return AccommodationRatingRepository(session)


@pytest.fixture
def user(session):
    user = User(id=uuid4(), name="Mark", email="mark@example.com")
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def camping(accommodations):
    return accommodations.add(
        Accommodation(
            id=uuid4(),
            name="Cosy Cabin",
            type=AccommodationType.CAMPING,
            country="Australia",
            city="Katoomba",
            address="1 Cliff Dr",
            description="tent site",
            price_per_night=Decimal("20.00"),
            availability_status=AvailabilityStatus.AVAILABLE,
            room_details=RoomDetails(
                room_count=1, bed_count=1, bed_types=[BedType.SINGLE]
            ),
        )
    )


@pytest.fixture
def hotel(accommodations):
    return accommodations.add(
        Accommodation(
            id=uuid4(),
            name="Grand Hotel",
            type=AccommodationType.HOTEL,
            country="Australia",
            city="Sydney",
            address="1 George St",
            description="city hotel",
            price_per_night=Decimal("250.00"),
            availability_status=AvailabilityStatus.AVAILABLE,
            room_details=RoomDetails(
                room_count=40, bed_count=60, bed_types=[BedType.QUEEN, BedType.KING]
            ),
        )
    )
