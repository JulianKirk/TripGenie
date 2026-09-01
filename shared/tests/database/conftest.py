"""Shared fixtures for the shared reference database service tests.

`shared_database_service` is importable because shared/ is pip-installed (see
shared/pyproject.toml) -- no PYTHONPATH needed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared_database_service.models import Base, City, Country, Currency
from shared_database_service.repository import (
    CityRepository,
    CountryRepository,
    CurrencyRepository,
)


@pytest.fixture
def session():
    """Fresh in-memory SQLite DB per test -- no dependency on database.py."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def countries(session):
    return CountryRepository(session)


@pytest.fixture
def cities(session):
    return CityRepository(session)


@pytest.fixture
def australia(session):
    country = Country.get_or_create(session, "australia")
    session.commit()
    return country


@pytest.fixture
def currencies(session):
    return CurrencyRepository(session)


@pytest.fixture
def aud(session, australia):
    currency = Currency.get_or_create(
        session, "australian dollar", "AUD", "$", 1.0, australia
    )
    session.commit()
    return currency


@pytest.fixture
def sydney(session, australia):
    city = City.get_or_create(session, "sydney", australia)
    session.commit()
    return city
