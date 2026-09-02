from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient
from student5_backend_service.ai_mode_client import AiModeClient
from student5_backend_service.app import create_app
from student5_backend_service.config import Settings

from .conftest import BUDGET_ID, database_handler, provider_handler, trips_handler


def test_ai_mode_client_sends_schema_and_parses_structured_analysis() -> None:
    captured: dict[str, object] = {}

    def ai_mode(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "aimode_1234",
                    "correlation_id": "budget_1234",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": json.dumps(
                        {
                            "overview": "Spending is within budget.",
                            "risks": ["Provider costs are incomplete."],
                            "recommendations": ["Keep a contingency reserve."],
                            "disclaimer": "Advisory only; review before acting.",
                        }
                    ),
                    "done": True,
                }
            },
        )

    client = AiModeClient(
        Settings(ai_mode_base_url="http://ai-mode.test"),
        transport=httpx.MockTransport(ai_mode),
    )
    result = client.generate(
        prompt="Analyse this budget.",
        correlation_id="budget_1234",
        metadata={"feature": "student-5-budget-analysis"},
    )
    client.close()

    assert captured["prompt"] == "Analyse this budget."
    assert captured["schema"]["required"] == [
        "overview",
        "risks",
        "recommendations",
        "disclaimer",
    ]
    assert result.analysis.recommendations == ["Keep a contingency reserve."]
    assert result.model == "qwen2.5:0.5b"


def test_budget_analysis_route_sends_only_selected_budget_context(
    settings: Settings,
) -> None:
    captured: dict[str, object] = {}
    attempts: list[dict[str, object]] = []

    def ai_mode(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        attempts.append(dict(captured))
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "aimode_5678",
                    "correlation_id": f"budget_{BUDGET_ID.replace('-', '')}",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": json.dumps(
                        {
                            "overview": "The remaining budget is AUD 699.70.",
                            "risks": ["Accommodation costs are unavailable."],
                            "recommendations": ["Reserve funds for missing costs."],
                            "disclaimer": "Advisory only; review before acting.",
                        }
                    ),
                    "done": True,
                }
            },
        )

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(database_handler),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(provider_handler),
        ai_mode_transport=httpx.MockTransport(ai_mode),
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/budgets/{BUDGET_ID}/ai-analysis",
            json={"question": "Where should I reduce spending?"},
        )

    assert response.status_code == 200, response.text
    prompt = str(captured["prompt"])
    assert "Where should I reduce spending?" in prompt
    assert "Total budget: AUD 1000.00" in prompt
    assert "Remaining budget: AUD 699.70 (complete: false)" in prompt
    assert "Recorded expenses: 1" in prompt
    assert '"trip_id":"trip_chunk3"' in prompt
    assert '"description":"Dinner"' in prompt
    assert captured["metadata"] == {
        "feature": "student-5-budget-analysis",
        "trip_id": "trip_chunk3",
        "attempt": "1",
    }
    assert len(attempts) == 1
    assert response.json()["data"]["analysis"]["recommendations"] == [
        "Reserve funds for missing costs."
    ]


def test_budget_analysis_retries_ungrounded_output_once(settings: Settings) -> None:
    attempts = 0

    def ai_mode(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        payload = json.loads(request.content)
        overview = (
            "The remaining budget is AUD 699.70."
            if attempts == 2
            else "The budget appears manageable."
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": f"aimode_{attempts}",
                    "correlation_id": payload["correlation_id"],
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": json.dumps(
                        {
                            "overview": overview,
                            "risks": [],
                            "recommendations": ["Keep a contingency reserve."],
                            "disclaimer": "Advisory only; review before acting.",
                        }
                    ),
                    "done": True,
                }
            },
        )

    app = create_app(
        settings,
        database_transport=httpx.MockTransport(database_handler),
        trips_transport=httpx.MockTransport(trips_handler),
        provider_transport=httpx.MockTransport(provider_handler),
        ai_mode_transport=httpx.MockTransport(ai_mode),
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/budgets/{BUDGET_ID}/ai-analysis",
            json={"question": "How am I tracking?"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == "aimode_2"
    assert attempts == 2