from __future__ import annotations

import logging

import httpx
import pytest
from backend_service.config import (
    AI_MAX_ATTEMPTS_MAX,
    AI_MAX_ATTEMPTS_MIN,
    Settings,
)


def ai_settings(**overrides: object) -> Settings:
    settings_kwargs: dict[str, object] = {
        "database_api_base_url": "http://database.test",
        "ollama_base_url": "http://ollama.test",
        "ollama_model": "qwen2.5:0.5b",
        "ollama_timeout_seconds": 1,
        "ollama_max_response_bytes": 16384,
        "ai_max_attempts": 2,
        "ai_max_context_items": 2,
    }
    settings_kwargs.update(overrides)
    return Settings(**settings_kwargs)


def test_ai_suggestions_success_builds_bounded_context_and_returns_drafts(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    database_api.items["item_2027_sydney_breakfast"] = {
        "id": "item_2027_sydney_breakfast",
        "trip_id": "trip_2027_sydney_getaway",
        "date": "2027-04-02",
        "start_time": "07:30",
        "end_time": "08:30",
        "title": "Harbour Breakfast",
        "location": "The Rocks",
        "description": "Breakfast before the ferry.",
        "category": "meal",
        "notes": "Avoid peak queues if possible.",
    }
    ollama_api.queue_json_body(
        """
        {
          "suggestions": [
            {
              "date": "2027-04-02",
              "start_time": "12:30",
              "end_time": "14:00",
              "title": "Waterside Lunch",
              "location": "Barangaroo",
              "description": "Relaxed lunch with harbour views.",
              "category": "meal",
              "notes": "Choose a quieter venue away from the ferry queues.",
              "rationale": "Fits the quiet afternoon goal after the morning walk."
            },
            {
              "date": "2027-04-02",
              "start_time": "14:30",
              "end_time": "16:00",
              "title": "Barangaroo Reserve Walk",
              "location": "Barangaroo Reserve",
              "description": "Gentle foreshore walk with places to rest.",
              "category": "activity",
              "notes": "Keep the pace light and stop for photos.",
              "rationale": "Adds a low-energy activity after lunch."
            }
          ]
        }
        """,
    )

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(ai_max_context_items=2),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Plan a gentle waterside afternoon.",
                "interests": "coffee, quiet views",
                "constraints": "avoid duplicate activities",
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["trip_id"] == "trip_2027_sydney_getaway"
    assert payload["requested_date"] == "2027-04-02"
    assert payload["persisted"] is False
    assert payload["approval_required"] is True
    assert payload["attempt_count"] == 1
    assert payload["model"] == "qwen2.5:0.5b"
    assert payload["prompt_asset"] == "runtime_ai_suggestions_v1.md"
    assert [item["title"] for item in payload["suggestions"]] == [
        "Waterside Lunch",
        "Barangaroo Reserve Walk",
    ]
    assert all(item["persisted"] is False for item in payload["suggestions"])
    assert all(
        item["approval_required"] is True for item in payload["suggestions"]
    )

    assert database_api.requests == [
        ("GET", "/internal/trips/trip_2027_sydney_getaway"),
        ("GET", "/internal/trips/trip_2027_sydney_getaway/itinerary-items"),
    ]
    assert len(ollama_api.requests) == 1
    ollama_request = ollama_api.requests[0]
    assert ollama_request["model"] == "qwen2.5:0.5b"
    assert ollama_request["stream"] is False
    assert ollama_request["options"] == {"temperature": 0}
    assert '"requested_date": "2027-04-02"' in ollama_request["prompt"]
    assert "Plan a gentle waterside afternoon." in ollama_request["prompt"]
    assert '"total_existing_items": 3' in ollama_request["prompt"]
    assert '"omitted_existing_items": 1' in ollama_request["prompt"]
    assert "Harbour Breakfast" in ollama_request["prompt"]
    assert "Harbour Walk" in ollama_request["prompt"]
    assert "Waterside Dinner" not in ollama_request["prompt"]
    assert ollama_request["format"]["type"] == "object"


def test_health_accepts_current_ollama_tags_metadata(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    ollama_api.models = [
        {
            "name": "qwen2.5:0.5b",
            "modified_at": "2026-08-29T09:00:00Z",
            "size": 934348800,
            "digest": "sha256:qwen-demo",
            "details": {
                "family": "qwen2",
                "families": ["qwen2"],
                "parameter_size": "0.5B",
                "quantization_level": "Q4_K_M",
            },
            "expires_at": "2026-08-29T10:00:00Z",
        },
    ]

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"]["dependencies"]["ollama"]["status"] == "ok"
    assert ollama_api.tag_requests == 1


def test_ai_suggestions_accept_current_ollama_generate_metadata(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    ollama_api.queue_response(
        httpx.Response(
            200,
            json={
                "model": "qwen2.5:0.5b",
                "created_at": "2026-08-29T09:00:00Z",
                "response": '{"suggestions":[]}',
                "done": True,
                "done_reason": "stop",
                "context": [101, 202, 303],
                "total_duration": 879685763,
                "load_duration": 22342342,
                "prompt_eval_count": 219,
                "prompt_eval_duration": 8134242,
                "eval_count": 48,
                "eval_duration": 5294187,
                "extra_metadata": {"ignored": True},
            },
        ),
    )

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Return an empty draft set with current Ollama metadata.",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["suggestions"] == []
    assert len(ollama_api.requests) == 1


def test_ai_suggestions_retries_once_then_succeeds(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    ollama_api.queue_json_body("{not valid json")
    ollama_api.queue_json_body(
        """
        {
          "suggestions": [
            {
              "date": "2027-04-02",
              "start_time": "11:00",
              "end_time": "12:00",
              "title": "Opera Bar Break",
              "location": "Sydney Opera House",
              "description": "Light break with a harbour view.",
              "category": "meal",
              "notes": "Keep it flexible.",
              "rationale": "Adds a relaxed stop after the existing walk."
            }
          ]
        }
        """,
    )

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Suggest one quiet midday stop.",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["attempt_count"] == 2
    assert len(ollama_api.requests) == 2
    assert (
        "The previous response could not be used."
        in ollama_api.requests[1]["prompt"]
    )
    assert "response body was not valid JSON" in ollama_api.requests[1]["prompt"]


@pytest.mark.parametrize(
    ("queued_body", "expected_fragment"),
    [
        ("{not valid json", "model did not return valid JSON"),
        (
            """
            {
              "suggestions": [
                {
                  "date": "2027-04-02",
                  "start_time": "12:30",
                  "end_time": "14:00",
                  "location": "Barangaroo",
                  "description": "Missing title should fail schema validation.",
                  "category": "meal"
                }
              ]
            }
            """,
            "title",
        ),
        (
            """
            {
              "suggestions": [
                {
                  "date": "2027-04-03",
                  "start_time": "12:30",
                  "end_time": "14:00",
                  "title": "Wrong Day Lunch",
                  "location": "Barangaroo",
                  "description": "Wrong date for the request.",
                  "category": "meal"
                }
              ]
            }
            """,
            "must match the requested date 2027-04-02",
        ),
        (
            """
            {
              "suggestions": [
                {
                  "date": "2027-04-02",
                  "start_time": "14:00",
                  "end_time": "13:00",
                  "title": "Backwards Timing",
                  "location": "Barangaroo",
                  "description": "Ends before it starts.",
                  "category": "meal"
                }
              ]
            }
            """,
            "must be earlier than end_time when both are provided",
        ),
        (
            """
            {
              "suggestions": [
                {
                  "date": "2027-04-02",
                  "start_time": "12:30",
                  "end_time": "14:00",
                  "title": "Invalid Category",
                  "location": "Barangaroo",
                  "description": "Category is not allowed.",
                  "category": "shopping"
                }
              ]
            }
            """,
            "category",
        ),
        (
            """
            {
              "suggestions": [
                {
                  "date": "2027-04-02",
                  "start_time": "09:00",
                  "end_time": "10:30",
                  "title": "Harbour Walk",
                  "location": "Circular Quay",
                  "description": "Duplicates the existing activity.",
                  "category": "activity"
                }
              ]
            }
            """,
            "duplicates the existing itinerary item",
        ),
        (
            """
            {
              "suggestions": [
                {
                  "date": "2027-04-02",
                  "start_time": "10:00",
                  "end_time": "11:00",
                  "title": "Coffee Catch-up",
                  "location": "Circular Quay",
                  "description": "Conflicts with the existing timed activity.",
                  "category": "meal"
                }
              ]
            }
            """,
            "conflicts with the existing itinerary item",
        ),
    ],
)
def test_ai_suggestions_invalid_outputs_fail_explicitly(
    client_factory,
    database_api,
    ollama_api,
    queued_body: str,
    expected_fragment: str,
) -> None:
    ollama_api.queue_json_body(queued_body)

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(ai_max_attempts=1),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Suggest one calm activity.",
            },
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_OUTPUT_INVALID"
    assert expected_fragment in str(response.json()["error"]["details"])


def test_ai_suggestions_retry_exhaustion_is_deterministic(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    duplicate_body = """
    {
      "suggestions": [
        {
          "date": "2027-04-02",
          "start_time": "09:00",
          "end_time": "10:30",
          "title": "Harbour Walk",
          "location": "Circular Quay",
          "description": "Still duplicates the existing itinerary.",
          "category": "activity"
        }
      ]
    }
    """
    ollama_api.queue_json_body(duplicate_body)
    ollama_api.queue_json_body(duplicate_body)

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(ai_max_attempts=2),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Retry the same duplicate output.",
            },
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_OUTPUT_INVALID"
    assert len(ollama_api.requests) == 2


def test_ai_suggestions_honour_retry_upper_boundary(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    invalid_body = """
    {
      "suggestions": [
        {
          "date": "2027-04-02",
          "start_time": "09:00",
          "end_time": "10:30",
          "title": "Harbour Walk",
          "location": "Circular Quay",
          "description": "Still duplicates the existing itinerary.",
          "category": "activity"
        }
      ]
    }
    """
    for _ in range(AI_MAX_ATTEMPTS_MAX):
        ollama_api.queue_json_body(invalid_body)

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(ai_max_attempts=AI_MAX_ATTEMPTS_MAX),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Use the maximum supported retry count.",
            },
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_OUTPUT_INVALID"
    assert len(ollama_api.requests) == AI_MAX_ATTEMPTS_MAX


@pytest.mark.parametrize(
    (
        "queued_response",
        "settings_override",
        "status_code",
        "error_code",
        "message_fragment",
    ),
    [
        (
            httpx.ReadTimeout(
                "slow",
                request=httpx.Request("POST", "http://ollama.test/api/generate"),
            ),
            ai_settings(),
            504,
            "DEPENDENCY_TIMEOUT",
            "Ollama did not respond before the configured timeout.",
        ),
        (
            httpx.ConnectError(
                "boom",
                request=httpx.Request("POST", "http://ollama.test/api/generate"),
            ),
            ai_settings(),
            503,
            "DEPENDENCY_UNAVAILABLE",
            "Ollama is unavailable.",
        ),
        (
            httpx.Response(200, text="{not json"),
            ai_settings(),
            502,
            "BAD_GATEWAY",
            "Ollama returned a malformed generate response.",
        ),
        (
            httpx.Response(
                200,
                json={
                    "model": "qwen2.5:0.5b",
                    "response": "x" * 200,
                    "done": True,
                    "done_reason": "stop",
                },
            ),
            ai_settings(ollama_max_response_bytes=80),
            502,
            "DEPENDENCY_RESPONSE_TOO_LARGE",
            "Ollama returned a response that exceeded the configured size limit.",
        ),
    ],
)
def test_ai_suggestions_dependency_failures_are_explicit(
    client_factory,
    database_api,
    ollama_api,
    queued_response: httpx.Response | Exception,
    settings_override: Settings,
    status_code: int,
    error_code: str,
    message_fragment: str,
) -> None:
    ollama_api.queue_response(queued_response)

    with client_factory(
        database_api.handle,
        settings_override=settings_override,
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "Test dependency failures.",
            },
        )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert message_fragment in response.json()["error"]["message"]
    assert len(ollama_api.requests) == 1


def test_health_is_degraded_when_ollama_is_unavailable_but_crud_still_works(
    client_factory,
    database_api,
) -> None:
    def failing_ollama(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=failing_ollama,
    ) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")
        trips_response = client.get("/api/trips")

    assert health_response.status_code == 200
    assert health_response.json()["data"]["status"] == "degraded"
    assert (
        health_response.json()["data"]["dependencies"]["ollama"]["status"]
        == "unavailable"
    )
    assert ready_response.status_code == 200
    assert ready_response.json()["data"]["status"] == "ok"
    assert trips_response.status_code == 200
    assert trips_response.json()["data"][0]["id"] == "trip_2027_sydney_getaway"


def test_ready_skips_live_ollama_probe_and_reports_non_authoritative_status(
    client_factory,
    database_api,
) -> None:
    ollama_calls = 0

    def timing_out_ollama(request: httpx.Request) -> httpx.Response:
        nonlocal ollama_calls
        ollama_calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=timing_out_ollama,
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    assert response.json()["data"]["dependencies"]["ollama"] == {
        "status": "not_checked",
        "service": "ollama",
        "detail": (
            "Ollama was not probed during /ready. Backend readiness is based "
            "on the database only."
        ),
        "code": None,
    }
    assert ollama_calls == 0


def test_ready_reuses_cached_ollama_status_without_reprobing(
    client_factory,
    database_api,
    ollama_api,
) -> None:
    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=ollama_api.handle,
    ) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")

    assert health_response.status_code == 200
    assert ready_response.status_code == 200
    assert ollama_api.tag_requests == 1
    assert ready_response.json()["data"]["dependencies"]["ollama"] == {
        "status": "ok",
        "service": "ollama",
        "detail": (
            "Ollama responded successfully and the configured model is "
            "available. This Ollama status is cached and non-authoritative for "
            "backend readiness."
        ),
        "code": None,
    }


@pytest.mark.parametrize(
    "ai_max_attempts",
    [
        0,
        AI_MAX_ATTEMPTS_MIN,
        2,
        AI_MAX_ATTEMPTS_MAX,
        AI_MAX_ATTEMPTS_MAX + 1,
        99,
    ],
)
def test_ai_max_attempt_settings_validation(ai_max_attempts: int) -> None:
    settings_kwargs = {
        "database_api_base_url": "http://database.test",
        "ollama_base_url": "http://ollama.test",
        "ai_max_attempts": ai_max_attempts,
    }

    if AI_MAX_ATTEMPTS_MIN <= ai_max_attempts <= AI_MAX_ATTEMPTS_MAX:
        settings = Settings(**settings_kwargs)
        assert settings.ai_max_attempts == ai_max_attempts
        return

    with pytest.raises(
        ValueError,
        match=(
            "STUDENT1_BACKEND_AI_MAX_ATTEMPTS must be between "
            f"{AI_MAX_ATTEMPTS_MIN} and {AI_MAX_ATTEMPTS_MAX}"
        ),
    ):
        Settings(**settings_kwargs)


@pytest.mark.parametrize(
    "raw_value",
    ["0", str(AI_MAX_ATTEMPTS_MAX + 1), "999"],
)
def test_ai_max_attempt_env_validation(monkeypatch, raw_value: str) -> None:
    monkeypatch.setenv("STUDENT1_BACKEND_DB_API_BASE_URL", "http://database.test")
    monkeypatch.setenv("STUDENT1_BACKEND_AI_MAX_ATTEMPTS", raw_value)

    with pytest.raises(
        ValueError,
        match=(
            "STUDENT1_BACKEND_AI_MAX_ATTEMPTS must be between "
            f"{AI_MAX_ATTEMPTS_MIN} and {AI_MAX_ATTEMPTS_MAX}"
        ),
    ):
        Settings.from_env()


def test_ai_suggestion_logs_redact_free_text_and_prompt_body(
    client_factory,
    database_api,
    ollama_api,
    caplog,
) -> None:
    database_api.trips["trip_2027_sydney_getaway"]["notes"] = (
        "SENSITIVE_TRIP_NOTE_SHOULD_NOT_BE_LOGGED"
    )
    ollama_api.queue_json_body('{"suggestions":[]}')

    caplog.set_level(logging.INFO, logger="backend_service.ai_suggestions")
    with client_factory(
        database_api.handle,
        settings_override=ai_settings(),
        ollama_handler=ollama_api.handle,
    ) as client:
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json={
                "requested_date": "2027-04-02",
                "goal": "SENSITIVE_GOAL_SHOULD_NOT_BE_LOGGED",
                "interests": "quiet cafes",
                "constraints": "keep walking short",
            },
        )

    assert response.status_code == 200
    assert "student1.ai_suggestions stage=start" in caplog.text
    assert "student1.ai_suggestions stage=success" in caplog.text
    assert "SENSITIVE_TRIP_NOTE_SHOULD_NOT_BE_LOGGED" not in caplog.text
    assert "SENSITIVE_GOAL_SHOULD_NOT_BE_LOGGED" not in caplog.text
    assert "Trip request context" not in caplog.text
