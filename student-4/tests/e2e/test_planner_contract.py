from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app as create_backend
from student4_backend_service.config import Settings as BackendSettings
from student4_database_service.app import create_app as create_database
from student4_database_service.config import Settings as DatabaseSettings
from student4_frontend_service.app import create_app as create_frontend
from student4_frontend_service.config import Settings as FrontendSettings

from tests.backend.test_activity_api import location_handler, public_payload
from tests.backend.test_itinerary_api import SYDNEY, FakeItinerary

if TYPE_CHECKING:
    from pathlib import Path


def test_planner_ui_resolves_real_catalogue_cards_and_records_human_review(
    tmp_path: Path,
) -> None:
    run_id = "magent_0123456789ab"
    run: dict[str, Any] = {
        "run_id": run_id,
        "feature": "student-4",
        "task": "Find a kayak activity",
        "status": "planning",
        "steps": [],
        "checks": [],
    }
    called: list[tuple[str, str]] = []

    def multi_agent(request: httpx.Request) -> httpx.Response:
        called.append((request.method, request.url.path))
        if request.url.path.endswith("/history"):
            return httpx.Response(200, json={"data": []})
        if request.url.path.endswith("/review"):
            body = json.loads(request.content)
            run.update(
                status="completed",
                human=body,
                final_result=body.get("corrected_result", run["result"]),
            )
        code = 202 if request.url.path == "/runs" else 200
        return httpx.Response(code, json={"data": run})

    entries: dict[str, dict[str, Any]] = {}
    trip = FakeItinerary().trips[0]

    def itinerary(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/trips":
            return httpx.Response(200, json={"data": [trip]})
        collection = f"/api/trips/{SYDNEY}/activities"
        if request.url.path == collection:
            return httpx.Response(200, json={"data": list(entries.values())})
        if request.method == "PUT" and request.url.path.startswith(collection + "/"):
            key = request.url.path.rsplit("/", 1)[-1]
            entries[key] = {
                "activity_id": key,
                "trip_id": SYDNEY,
                "date": trip["start_date"],
                **json.loads(request.content),
            }
            return httpx.Response(200, json={"data": entries[key]})
        return httpx.Response(404)

    database = create_database(
        DatabaseSettings(database_url=f"sqlite:///{tmp_path / 'activities.db'}")
    )
    backend = create_backend(
        BackendSettings(multi_agent_enabled=True),
        database_transport=httpx.ASGITransport(app=database),
        location_transport=httpx.MockTransport(location_handler),
        multi_agent_transport=httpx.MockTransport(multi_agent),
        itinerary_transport=httpx.MockTransport(itinerary),
    )
    frontend = create_frontend(
        FrontendSettings(), transport=httpx.ASGITransport(app=backend)
    )
    with (
        TestClient(database),
        TestClient(backend) as api,
        TestClient(frontend) as browser,
    ):
        created = api.post("/activity", json=public_payload("Planner Contract Kayak"))
        assert created.status_code == 201
        activity_id = created.json()["id"]
        start = browser.post(
            "/suggestions/ask",
            data={"mode": "planner", "question": "Find a kayak activity"},
            headers={"HX-Request": "true"},
        )
        assert "every 2s" in start.text
        run.update(
            status="awaiting_human",
            result={
                "type": "final",
                "parts": [
                    {"type": "text", "text": "Consider this kayak activity."},
                    {"type": "activity", "activity_id": activity_id},
                ],
            },
            steps=[
                {
                    "agent": "worker",
                    "attempt": 1,
                    "status": "completed",
                    "tools": [
                        {
                            "tool": "activities_search",
                            "arguments": {},
                            "status": "success",
                            "duration_ms": 1,
                            "result": {
                                "structuredContent": {
                                    "source": "student-4",
                                    "ok": True,
                                    "data": {"items": [{"id": activity_id}]},
                                }
                            },
                        }
                    ],
                }
            ],
        )
        fetched = browser.get(f"/planner/{run_id}")
        assert "Planner Contract Kayak" in fetched.text
        assert "activities_search" in fetched.text
        assert "every 2s" not in fetched.text
        accepted = browser.post(
            f"/planner/{run_id}/review",
            data={
                "decision": "approve",
                "reviewer": "Test traveller",
                f"choice_{activity_id}": "approve",
                "trip_id": SYDNEY,
            },
        )
        assert "Human decisions recorded" in accepted.text
        assert "Test traveller" in accepted.text
        assert "Itinerary updated" in accepted.text
        assert activity_id in entries
        evidence = browser.get(f"/planner/{run_id}/history")
        assert evidence.json()["run"]["human"]["decision"] == "approve"
        assert evidence.json()["run"]["steps"][0]["tools"][0]["status"] == "success"
    assert called == [
        ("POST", "/runs"),
        ("GET", f"/runs/{run_id}"),
        ("GET", f"/runs/{run_id}"),
        ("GET", f"/runs/{run_id}"),
        ("POST", f"/runs/{run_id}/review"),
        ("GET", f"/runs/{run_id}"),
        ("GET", f"/runs/{run_id}/history"),
    ]
