from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from student5_database_service.app import create_app
from student5_database_service.config import Settings


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "tripgenie.db"


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(sqlite_path=database_path, seed_data=False))
    with TestClient(app) as test_client:
        yield test_client
