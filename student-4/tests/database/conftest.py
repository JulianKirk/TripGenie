"""Real temporary-SQLite fixtures for Student 4 database tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker
from student4_database_service.config import Settings
from student4_database_service.database import (
    create_engine_and_session,
    initialize_database,
)
from student4_database_service.repository import ActivityRepository
from student4_database_service.schemas import ActivityWrite
from student4_database_service.seed_data import seed_categories

SYDNEY = {
    "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
    "city_id": "96318064-7cdc-54a8-a8d8-bb2c67d12c3e",
}
MELBOURNE = {
    "country_id": "36c95358-ac43-537d-ab58-8f4123ae55c0",
    "city_id": "bc37aae2-9766-5646-93dd-09fc42211aa6",
}


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'activities.db'}", seed=False
    )
    engine, factory = create_engine_and_session(settings)
    initialize_database(engine)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as database_session:
        seed_categories(database_session)
        yield database_session


@pytest.fixture
def activities(session: Session) -> ActivityRepository:
    return ActivityRepository(session)


@pytest.fixture
def activity_payload() -> Callable[..., ActivityWrite]:
    def build(**updates: Any) -> ActivityWrite:
        payload: dict[str, Any] = {
            "name": "Harbour walk",
            "description": "A guided Sydney foreshore tour.",
            "price": "45.00",
            "pricing_basis": "PER_PERSON",
            "duration_minutes": 60,
            "minimum_age": 8,
            "maximum_age": 80,
            "minimum_participants": 1,
            "maximum_participants": 10,
            "booking_required": True,
            "wheelchair_accessible": True,
            "step_free_access": True,
            "accessible_toilet": None,
            "is_active": True,
            "location_details": {**SYDNEY, "street": "Circular Quay"},
            "categories": ["OUTDOOR", "TOUR"],
            "availability_schedules": [
                {
                    "recurring_weekly": True,
                    "day_of_week": "SATURDAY",
                    "start_time": "09:00",
                    "end_time": "11:00",
                }
            ],
        }
        payload.update(updates)
        return ActivityWrite.model_validate(payload)

    return build
