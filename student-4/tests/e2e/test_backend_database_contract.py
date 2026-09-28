from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app as create_backend
from student4_backend_service.config import Settings as BackendSettings
from student4_database_service.app import create_app as create_database
from student4_database_service.config import Settings as DatabaseSettings

from tests.backend.test_activity_api import location_handler, public_payload

if TYPE_CHECKING:
    from pathlib import Path


def test_public_crud_round_trip_uses_real_database_service(tmp_path: Path) -> None:
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

            query = {
                "text": "kayaking",
                "location": {"country": "Australia", "city": "Sydney"},
                "price": {"max": "89.50"},
                "limit": 1,
            }
            searched = client.request("QUERY", "/activity", json=query)
            assert searched.status_code == 200, searched.text
            assert [row["id"] for row in searched.json()["activities"]] == [activity_id]
            assert searched.json()["total"] == 1

            too_expensive = client.request(
                "QUERY", "/activity", json={**query, "price": {"max": "89.49"}}
            )
            assert too_expensive.status_code == 200, too_expensive.text
            assert too_expensive.json()["activities"] == []

            next_page = client.request(
                "QUERY", "/activity", json={**query, "offset": 1}
            )
            assert next_page.status_code == 200, next_page.text
            assert next_page.json()["activities"] == []
            assert next_page.json()["total"] == 1

            deleted = client.delete(f"/activity/{activity_id}")
            assert deleted.status_code == 200
