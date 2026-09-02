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
    LocationDetails,
    RoomDetails,
)
from database_service.repository import AccommodationRepository
from database_service.seed_data import place

# The shared reference service's ids for these places. There are no Country or
# City rows to build here any more -- those tables belong to the shared service
# and this one only stores their ids.
SYDNEY = place("australia", "sydney")
KATOOMBA = place("australia", "katoomba")


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
def camping(accommodations):
    return accommodations.add(
        Accommodation(
            id=uuid4(),
            name="Cosy Cabin",
            type=AccommodationType.CAMPING,
            description="tent site",
            price_per_night=Decimal("20.00"),
            availability_status=AvailabilityStatus.AVAILABLE,
            location_details=LocationDetails(
                **KATOOMBA, street="Cliff Dr", street_number=1
            ),
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
            description="city hotel",
            price_per_night=Decimal("250.00"),
            availability_status=AvailabilityStatus.AVAILABLE,
            location_details=LocationDetails(
                **SYDNEY, street="George St", street_number=1
            ),
            room_details=RoomDetails(
                room_count=40, bed_count=60, bed_types=[BedType.QUEEN, BedType.KING]
            ),
        )
    )
