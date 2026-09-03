from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app as create_backend
from student4_backend_service.config import Settings as BackendSettings
from student4_database_service.app import create_app as create_database
from student4_database_service.config import Settings as DatabaseSettings

from tests.backend.test_activity_api import location_handler, public_payload


def test_public_crud_round_trip_uses_real_database_service(tmp_path) -> None:
    database = create_database(
        DatabaseSettings(
            database_url=f"sqlite:///{tmp_path / 'activities.db'}", seed=True
        )
    )
    with TestClient(database):
        backend = create_backend(
            BackendSettings(),
            database_transport=httpx.ASGITransport(app=database),
            location_transport=httpx.MockTransport(location_handler),
        )
        client_context = TestClient(backend)
        with client_context as client:
            created = client.post("/activity", json=public_payload("Contract Kayak"))
            assert created.status_code == 201, created.text
            activity_id = created.json()["id"]

            fetched = client.get(f"/activity/{activity_id}")
            assert fetched.status_code == 200
            assert fetched.json()["name"] == "Contract Kayak"

            listed = client.get("/activity")
            assert activity_id in {row["id"] for row in listed.json()["activities"]}

            deleted = client.delete(f"/activity/{activity_id}")
            assert deleted.status_code == 200
