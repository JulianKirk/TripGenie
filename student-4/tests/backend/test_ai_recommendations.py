from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from student4_backend_service.ai_mode_client import AiModeClient
from student4_backend_service.config import Settings
from student4_backend_service.schemas import (
    ActivityEvaluationDraft,
    RecommendationPlanRequest,
)

from tests.backend.test_activity_api import FakeDatabase, location_handler
from tests.backend.test_itinerary_api import SYDNEY, FakeItinerary


def _ai_response(response: dict[str, object]) -> dict[str, object]:
    return {
        "data": {
            "run_id": "run-activity-1",
            "model": "qwen2.5:3b",
            "provider": "ollama",
            "response": json.dumps(response),
            "done": True,
        }
    }


def test_ai_settings_are_optional_and_validate_positive_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MODE_URL", "http://ai-mode.test/")
    monkeypatch.setenv("AI_MODE_TIMEOUT", "75")
    monkeypatch.setenv("AI_PROMPT_MAX_CHARS", "12000")
    monkeypatch.setenv("AI_MAX_CANDIDATES", "12")

    settings = Settings.from_env()

    assert settings.ai_mode_url == "http://ai-mode.test"
    assert settings.ai_mode_timeout == 75
    assert settings.ai_prompt_max_chars == 12000
    assert settings.ai_max_candidates == 12

    with pytest.raises(ValueError, match="ai_max_candidates"):
        Settings(ai_max_candidates=0)

    assert Settings().ai_prompt_max_chars == 12_000


def test_ai_request_and_evaluation_draft_are_strict() -> None:
    request = RecommendationPlanRequest(question="  Find outdoor ideas  ")
    assert request.question == "Find outdoor ideas"

    with pytest.raises(ValidationError):
        RecommendationPlanRequest(question="")

    with pytest.raises(ValidationError, match="mutually exclusive"):
        ActivityEvaluationDraft.model_validate(
            {
                "overview": "A result and retry cannot coexist.",
                "suggestions": [
                    {
                        "activity_id": "0f2b1c4e-aaaa-bbbb-cccc-000000000004",
                        "reason": "It is outdoors.",
                    }
                ],
                "considerations": [],
                "disclaimer": "Review before adding.",
                "revised_query": {"duration_minutes": {"max": 180}},
                "revision_explanation": "Allow a longer activity.",
            }
        )


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


def test_plan_endpoint_applies_selected_trip_constraints() -> None:
    from student4_backend_service.app import create_app

    ai_requests: list[dict[str, Any]] = []

    def ai(request: httpx.Request) -> httpx.Response:
        ai_requests.append(cast("dict[str, Any]", json.loads(request.content)))
        return httpx.Response(
            200,
            json=_ai_response(
                {
                    "query": {
                        "categories": {"codes": ["OUTDOOR"], "match": "ANY"},
                        "sort": "PRICE_DESC",
                    },
                    "summary": "outdoor activities",
                }
            ),
        )

    app = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
        ai_mode_transport=httpx.MockTransport(ai),
    )
    with TestClient(app) as client:
        response = client.post(
            "/activity/recommendations/plan",
            json={"question": "Something outdoors", "trip_id": SYDNEY},
        )

    assert response.status_code == 200
    assert response.json()["query"] == {
        "location": {"country": "australia", "city": "sydney"},
        "categories": {"codes": ["OUTDOOR"], "match": "ANY"},
        "party_size": 2,
        "sort": "NAME_ASC",
        "include_inactive": False,
        "limit": 20,
        "offset": 0,
    }
    assert response.json()["trip_context_available"] is True
    assert response.json()["summary"] == (
        "outdoor activities for Sydney Getaway in Sydney (2 travellers)"
    )
    assert "Sydney Getaway" in ai_requests[0]["prompt"]
    assert "2027-04-01" in ai_requests[0]["prompt"]
    query_schema = ai_requests[0]["schema"]["$defs"]["ActivityQuery"]["properties"]
    assert "sort" not in query_schema


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


def test_evaluation_searches_real_rows_and_grounds_recommendations() -> None:
    from student4_backend_service.app import create_app

    database = FakeDatabase()

    def ai(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ai_response(
                {
                    "overview": "The harbour activity fits the request.",
                    "suggestions": [
                        {
                            "activity_id": "0f2b1c4e-aaaa-bbbb-cccc-000000000004",
                            "reason": "It is a two-hour outdoor activity in Sydney.",
                        }
                    ],
                    "considerations": ["External booking is required."],
                    "disclaimer": "Review availability before adding it.",
                }
            ),
        )

    app = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        database_transport=httpx.MockTransport(database.handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
        ai_mode_transport=httpx.MockTransport(ai),
    )
    with TestClient(app) as client:
        from tests.backend.test_activity_api import public_payload

        assert client.post("/activity", json=public_payload()).status_code == 201
        database.calls.clear()
        response = client.post(
            "/activity/recommendations/evaluate",
            json={
                "question": "An outdoor activity",
                "query": {"categories": {"codes": ["OUTDOOR"], "match": "ANY"}},
                "summary": "outdoor activities",
                "attempt": 1,
            },
        )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "complete"
    assert result["matched_count"] == 1
    assert result["evaluated_count"] == 1
    assert result["query"]["sort"] == "NAME_ASC"
    assert result["recommended"][0]["activity"]["name"] == "Harbour Kayak"
    assert result["recommended"][0]["reason"].startswith("It is a two-hour")
    assert {method for method, _, _ in database.calls} == {"QUERY", "GET"}


def test_first_evaluation_can_return_one_revised_search() -> None:
    from student4_backend_service.app import create_app

    def ai(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ai_response(
                {
                    "overview": "The first search was too narrow.",
                    "suggestions": [],
                    "considerations": [],
                    "disclaimer": "Review the revised search.",
                    "revised_query": {"duration_minutes": {"max": 180}},
                    "revised_summary": "activities lasting up to three hours",
                    "revision_explanation": "Allow activities up to three hours.",
                }
            ),
        )

    app = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
        ai_mode_transport=httpx.MockTransport(ai),
    )
    with TestClient(app) as client:
        response = client.post(
            "/activity/recommendations/evaluate",
            json={
                "question": "A short activity",
                "query": {"duration_minutes": {"max": 60}},
                "summary": "activities up to one hour",
                "attempt": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "retry"
    assert response.json()["attempt"] == 2
    assert response.json()["query"]["duration_minutes"] == {"max": 180}
    assert response.json()["summary"] == "activities lasting up to three hours"
    assert response.json()["revision_explanation"] == (
        "Allow activities up to three hours."
    )


def test_trip_retry_cannot_weaken_destination_or_party_size() -> None:
    from student4_backend_service.app import create_app

    def ai(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ai_response(
                {
                    "overview": "Try a broader search.",
                    "suggestions": [],
                    "considerations": [],
                    "disclaimer": "Review the revised search.",
                    "revised_query": {
                        "location": {"country": "australia"},
                        "party_size": 1,
                        "duration_minutes": {"max": 180},
                    },
                    "revised_summary": "longer activities",
                    "revision_explanation": "Allow more time.",
                }
            ),
        )

    app = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        database_transport=httpx.MockTransport(FakeDatabase().handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
        ai_mode_transport=httpx.MockTransport(ai),
    )
    with TestClient(app) as client:
        response = client.post(
            "/activity/recommendations/evaluate",
            json={
                "question": "Something relaxed",
                "trip_id": SYDNEY,
                "query": {
                    "location": {"country": "australia", "city": "sydney"},
                    "party_size": 2,
                },
                "summary": "relaxed Sydney activities",
                "attempt": 1,
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "The revised search weakened trip constraints."


def test_inactive_hydrated_candidates_do_not_reach_ai() -> None:
    from student4_backend_service.app import create_app

    from tests.backend.test_activity_api import public_payload

    database = FakeDatabase()
    candidate_counts: list[int] = []

    def database_handler(request: httpx.Request) -> httpx.Response:
        response = database.handle(request)
        if request.method == "GET" and request.url.path.endswith(
            "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
        ):
            body = response.json()
            body["is_active"] = False
            return httpx.Response(200, json=body)
        return response

    def ai(request: httpx.Request) -> httpx.Response:
        prompt = cast("dict[str, Any]", json.loads(request.content))["prompt"]
        marker = "Context JSON:\n"
        context = json.loads(prompt.split(marker, 1)[1])
        candidate_counts.append(len(context["candidates"]))
        return httpx.Response(
            200,
            json=_ai_response(
                {
                    "overview": "No active candidates remain.",
                    "suggestions": [],
                    "considerations": [],
                    "disclaimer": "Try another search.",
                }
            ),
        )

    app = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        database_transport=httpx.MockTransport(database_handler),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
        ai_mode_transport=httpx.MockTransport(ai),
    )
    with TestClient(app) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            "/activity/recommendations/evaluate",
            json={
                "question": "An active activity",
                "query": {},
                "summary": "active activities",
            },
        )

    assert response.status_code == 200
    assert response.json()["evaluated_count"] == 0
    assert candidate_counts == [0]


def test_unconfigured_ai_and_malformed_output_are_reported() -> None:
    from student4_backend_service.app import create_app

    dependencies = {
        "database_transport": httpx.MockTransport(FakeDatabase().handle),
        "location_transport": httpx.MockTransport(location_handler),
        "itinerary_transport": httpx.MockTransport(FakeItinerary().handle),
    }
    unconfigured = create_app(Settings(), **dependencies)
    with TestClient(unconfigured) as client:
        unavailable = client.post(
            "/activity/recommendations/plan", json={"question": "Outdoor ideas"}
        )
    assert unavailable.status_code == 503

    malformed = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        **dependencies,
        ai_mode_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json=_ai_response({"not": "a search plan"}),
            )
        ),
    )
    with TestClient(malformed) as client:
        bad_output = client.post(
            "/activity/recommendations/plan", json={"question": "Outdoor ideas"}
        )
    assert bad_output.status_code == 502


def test_evaluation_rejects_an_activity_outside_authoritative_results() -> None:
    from student4_backend_service.app import create_app

    from tests.backend.test_activity_api import public_payload

    database = FakeDatabase()

    def ai(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ai_response(
                {
                    "overview": "A fabricated identifier must not be accepted.",
                    "suggestions": [
                        {
                            "activity_id": "99999999-9999-9999-9999-999999999999",
                            "reason": "Not grounded in the search result.",
                        }
                    ],
                    "considerations": [],
                    "disclaimer": "Review before adding.",
                }
            ),
        )

    app = create_app(
        Settings(ai_mode_url="http://ai-mode.test"),
        database_transport=httpx.MockTransport(database.handle),
        location_transport=httpx.MockTransport(location_handler),
        itinerary_transport=httpx.MockTransport(FakeItinerary().handle),
        ai_mode_transport=httpx.MockTransport(ai),
    )
    with TestClient(app) as client:
        assert client.post("/activity", json=public_payload()).status_code == 201
        response = client.post(
            "/activity/recommendations/evaluate",
            json={
                "question": "Outdoor ideas",
                "query": {},
                "summary": "outdoor activities",
            },
        )

    assert response.status_code == 502
    assert "outside the search results" in response.json()["detail"]
