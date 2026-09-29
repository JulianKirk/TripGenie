from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.ai_mode_client import AiModeClient
from student4_backend_service.config import Settings

from tests.backend.test_activity_api import FakeDatabase, location_handler
from tests.backend.test_itinerary_api import SYDNEY, FakeItinerary


def test_ai_client_returns_generated_json_with_provenance() -> None:
    captured: dict[str, object] = {}

    def generate(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "run-activity-1",
                    "model": "qwen2.5:3b",
                    "provider": "ollama",
                    "response": '{"summary":"outdoor ideas","query":{}}',
                    "done": True,
                }
            },
        )

    client = AiModeClient(
        Settings(ai_mode_url="http://ai-mode.test"),
        transport=httpx.MockTransport(generate),
    )
    answer = asyncio.run(
        client.generate(
            prompt="Plan a search",
            schema={"type": "object"},
            correlation_id="student4-plan-1",
            metadata={"feature": "activity-search-plan"},
        )
    )
    asyncio.run(client.aclose())

    assert answer.response == '{"summary":"outdoor ideas","query":{}}'
    assert (answer.run_id, answer.model, answer.provider) == (
        "run-activity-1",
        "qwen2.5:3b",
        "ollama",
    )
    assert captured == {
        "prompt": "Plan a search",
        "schema": {"type": "object"},
        "correlation_id": "student4-plan-1",
        "metadata": {"feature": "activity-search-plan"},
    }


def test_trip_directory_supports_the_optional_ai_context_picker() -> None:
    from student4_backend_service.app import create_app

    app = create_app(
        Settings(),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
    )
    with TestClient(app) as client:
        response = client.get("/activity/trips")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["trips"][0]["id"] == SYDNEY
    assert response.json()["trips"][0]["name"] == "Sydney Getaway"


def test_legacy_ai_routes_and_prompts_are_removed() -> None:
    from importlib.resources import files

    from student4_backend_service.app import create_app

    with TestClient(create_app(Settings())) as client:
        for path in (
            "/activity/recommendations/plan",
            "/activity/recommendations/evaluate",
        ):
            assert client.post(path, json={}).status_code == 404
        assert "/activity/assistant" in client.get("/openapi.json").json()["paths"]
    prompts = files("student4_backend_service").joinpath("prompts")
    assert prompts.joinpath("activity_assistant_v1.md").is_file()
    assert not prompts.joinpath("activity_search_plan_v1.md").is_file()
    assert not prompts.joinpath("activity_recommendations_v1.md").is_file()
