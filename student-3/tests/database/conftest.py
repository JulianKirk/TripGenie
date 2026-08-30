from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from student3_database_service.app import create_app
from student3_database_service.config import Settings
from student3_database_service.repository import DatabaseService


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "tripgenie.db"


@pytest.fixture
def settings(database_path: Path) -> Settings:
    return Settings(sqlite_path=database_path)


@pytest.fixture
def service(settings: Settings) -> DatabaseService:
    return DatabaseService(settings)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
