from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
from fastapi.testclient import TestClient
from student4_backend_service.app import create_app
from student4_backend_service.config import Settings

from tests.backend.test_activity_api import (
    CITY_ID,
    COUNTRY_ID,
    FakeDatabase,
    location_handler,
)

ACTIVITY = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
DETAIL: dict[str, Any] = {
    "id": ACTIVITY,
    "name": "Harbour walk",
    "description": "A real walk",
    "price": "45.00",
    "pricing_basis": "PER_PERSON",
    "duration_minutes": 60,
    "minimum_participants": 1,
    "booking_required": False,
    "is_active": True,
    "categories": ["OUTDOOR"],
    "location_details": {"country": "australia", "city": "sydney"},
    "availability_schedules": [
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "recurring_weekly": True,
            "day_of_week": "SATURDAY",
            "start_time": "09:00",
            "end_time": "11:00",
        }
    ],
}


def card_database(**changes: Any) -> FakeDatabase:
    database = FakeDatabase()
    database.records[ACTIVITY] = {
        **deepcopy(DETAIL),
        **changes,
        "location_details": {
            "id": "33333333-3333-3333-3333-333333333333",
            "country_id": COUNTRY_ID,
            "city_id": CITY_ID,
        },
    }
    return database


def run_agent(
    answer: dict[str, Any],
    *,
    question: str = "Find walks",
    status: int = 200,
    database: FakeDatabase | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def ai(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/generate"
        requests.append(json.loads(request.content))
        return httpx.Response(status, json=answer)

    with TestClient(
        create_app(
            Settings(ai_mode_url="http://ai.test", assistant_enabled=True),
            database_transport=httpx.MockTransport(
                (database or card_database()).handle
            ),
            location_transport=httpx.MockTransport(location_handler),
            ai_mode_transport=httpx.MockTransport(ai),
        )
    ) as client:
        response = client.post("/activity/assistant", json={"question": question})
    assert response.status_code == 200
    return response.json(), requests


def generated(
    *, card: str | None = ACTIVITY, text: str = "Model authored answer"
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if card:
        parts.append({"type": "activity", "activity_id": card})
    return {
        "data": {
            "run_id": "shared-agent",
            "model": "model",
            "provider": "ollama",
            "done": True,
            "response": json.dumps({"type": "final", "parts": parts}),
            "tools": [
                {
                    "tool": "activities_search",
                    "arguments": {"filters": {}},
                    "status": "success",
                    "duration_ms": 1,
                    "result": {
                        "structuredContent": {
                            "source": "student-4",
                            "ok": True,
                            "correlation_id": "mcp-test",
                            "data": {"items": [DETAIL]},
                        }
                    },
                }
            ],
        }
    }


def test_shared_agent_receives_question_without_parsing_and_retains_model_answer() -> (
    None
):
    question = "Next Friday, under twenty dollars for the whole group, no booking"
    result, requests = run_agent(
        generated(), question=question, database=card_database(price="900.00")
    )
    assert len(requests) == 1
    assert json.loads(requests[0]["prompt"])["question"] == question
    assert requests[0]["system"]
    assert result["parts"][0]["text"] == "Model authored answer"
    assert result["activities"][ACTIVITY]["price"] == "900.00"
    assert result["tools"][0]["result"]["structuredContent"]["data"]["items"]


def test_unseen_reference_is_rejected_before_card_lookup() -> None:
    result, _ = run_agent(generated(card="11111111-1111-1111-1111-111111111111"))
    assert result["status"] == "error"
    assert result["activities"] == {}
    assert len(result["tools"]) == 1


def test_failed_tool_cannot_authorize_activity_card() -> None:
    answer = generated()
    answer["data"]["tools"][0]["status"] = "error"
    result, _ = run_agent(answer)
    assert result["status"] == "error"


def test_shared_failure_preserves_partial_trace() -> None:
    trace = generated()["data"]["tools"]
    result, _ = run_agent(
        {"error": {"code": "DEPENDENCY_TIMEOUT"}, "tools": trace}, status=504
    )
    assert result["status"] == "error"
    assert result["tools"][0]["status"] == "success"


def test_unavailable_card_preserves_model_text_and_missing_reference() -> None:
    result, _ = run_agent(generated(), database=FakeDatabase())
    assert result["status"] == "complete"
    assert result["parts"][0]["text"] == "Model authored answer"
    assert result["unavailable_activity_ids"] == [ACTIVITY]


def test_cross_domain_trace_and_text_only_answer_are_preserved() -> None:
    answer = generated(card=None, text="Budget summary from the model")
    answer["data"]["tools"][0]["tool"] = "budgets_get_summary"
    result, _ = run_agent(answer)
    assert result["status"] == "complete"
    assert result["tools"][0]["tool"] == "budgets_get_summary"
    assert result["parts"][0]["text"] == "Budget summary from the model"


def test_disabled_assistant_does_not_call_shared_service() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        message = "No generation should run"
        raise AssertionError(message)

    with TestClient(
        create_app(
            Settings(assistant_enabled=False),
            ai_mode_transport=httpx.MockTransport(unexpected),
        )
    ) as client:
        response = client.post("/activity/assistant", json={"question": "Find walks"})
    assert response.json()["status"] == "error"
    assert "disabled" in response.json()["error"]
