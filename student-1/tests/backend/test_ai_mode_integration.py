from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from ai_mode_service.app import create_app as create_shared_ai_mode_app
from ai_mode_service.config import Settings as SharedAiModeSettings
from backend_service.ai_contract import AI_MODE_PROMPT_MAX_CHARS_DEFAULT
from backend_service.ai_suggestions import (
    AiModeSuggestionEnvelope,
    AiSuggestionRequest,
    build_budgeted_prompt,
    build_prompt_context,
    prepare_cross_service_prompt_context,
    select_cross_service_records,
)
from backend_service.app import create_app as create_student_backend_app
from backend_service.config import Settings as StudentBackendSettings
from backend_service.errors import ApiError
from backend_service.models import (
    ItineraryItemRecord,
    TripAccommodationDetail,
    TripAccommodationRecord,
    TripActivityDetail,
    TripActivityRecord,
    TripRecord,
    TripTransportDetail,
    TripTransportRecord,
)
from conftest import FakeDatabaseApi
from fastapi.testclient import TestClient


class CountingASGITransport(httpx.AsyncBaseTransport):
    def __init__(self, app) -> None:
        self.request_count = 0
        self.paths: list[str] = []
        self._transport = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.paths.append(request.url.path)
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


class FakeOllamaProviderApi:
    def __init__(self) -> None:
        self.tag_requests = 0
        self.generate_requests: list[dict[str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()

        if path == "/api/tags" and method == "GET":
            self.tag_requests += 1
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen2.5:0.5b",
                            "model": "qwen2.5:0.5b",
                            "modified_at": "2026-08-31T11:00:00Z",
                            "size": 934348800,
                            "digest": "sha256:qwen-demo",
                            "details": {"family": "qwen2"},
                        }
                    ]
                },
            )

        if path == "/api/generate" and method == "POST":
            payload = json.loads(request.content.decode("utf-8"))
            self.generate_requests.append(payload)
            return httpx.Response(
                200,
                json={
                    "model": "qwen2.5:0.5b",
                    "created_at": "2026-08-31T11:00:00Z",
                    "response": '{"suggestions":[]}',
                    "done": True,
                    "done_reason": "stop",
                    "context": [1, 2, 3],
                    "total_duration": 5043500667,
                    "load_duration": 5025959,
                    "prompt_eval_count": 26,
                    "prompt_eval_duration": 325953000,
                    "eval_count": 290,
                    "eval_duration": 4709213000,
                },
            )

        return httpx.Response(404, json={"error": "not found"})


def student_settings(**overrides: object) -> StudentBackendSettings:
    settings = {
        "database_api_base_url": "http://database.test",
        "ai_mode_base_url": "http://shared-ai-mode.test",
        "ai_mode_timeout_seconds": 1,
        "ai_mode_max_prompt_chars": AI_MODE_PROMPT_MAX_CHARS_DEFAULT,
    }
    settings.update(overrides)
    return StudentBackendSettings(**settings)


def shared_settings(*, max_prompt_chars: int) -> SharedAiModeSettings:
    return SharedAiModeSettings(
        service_name="ai-mode",
        ollama_base_url="http://ollama.test",
        default_model="qwen2.5:0.5b",
        allowed_models=("qwen2.5:0.5b",),
        ollama_timeout_seconds=1.0,
        max_prompt_chars=max_prompt_chars,
        max_schema_chars=8000,
        max_response_bytes=16384,
    )


@contextmanager
def integrated_client(
    *,
    database_api: FakeDatabaseApi,
    ollama_api: FakeOllamaProviderApi,
    backend_settings: StudentBackendSettings,
    shared_service_settings: SharedAiModeSettings,
) -> Iterator[tuple[TestClient, CountingASGITransport]]:
    shared_app = create_shared_ai_mode_app(
        shared_service_settings,
        ollama_transport=httpx.MockTransport(ollama_api.handle),
    )
    with TestClient(shared_app):
        transport = CountingASGITransport(shared_app)
        backend_app = create_student_backend_app(
            backend_settings,
            database_transport=httpx.MockTransport(database_api.handle),
            ai_mode_transport=transport,
        )
        with TestClient(backend_app) as client:
            yield client, transport


def extract_prompt_context(prompt: str) -> dict[str, object]:
    start_marker = "Trip request context:\n"
    end_marker = "\n\nTyped retry context for this attempt:"
    context_start = prompt.index(start_marker) + len(start_marker)
    context_end = prompt.index(end_marker)
    return json.loads(prompt[context_start:context_end])


def trip_record(database_api: FakeDatabaseApi) -> TripRecord:
    return TripRecord.model_validate(database_api.trips["trip_2027_sydney_getaway"])


def trip_items(database_api: FakeDatabaseApi) -> list[ItineraryItemRecord]:
    return [
        ItineraryItemRecord.model_validate(item)
        for item in database_api.items.values()
        if item["trip_id"] == "trip_2027_sydney_getaway"
    ]


def make_long_text(prefix: str, length: int) -> str:
    base = f"{prefix}港"
    repeated = (base * ((length // len(base)) + 2))[:length]
    return repeated


def add_maximal_context_items(database_api: FakeDatabaseApi) -> None:
    database_api.trips["trip_2027_sydney_getaway"]["notes"] = make_long_text(
        "trip-note-",
        2000,
    )
    for index in range(10):
        item_id = f"item_2027_sydney_budget_{index:02d}"
        database_api.items[item_id] = {
            "id": item_id,
            "trip_id": "trip_2027_sydney_getaway",
            "date": "2027-04-02" if index < 6 else "2027-04-03",
            "start_time": f"{10 + (index % 6):02d}:00",
            "end_time": f"{11 + (index % 6):02d}:00",
            "title": make_long_text(f"title-{index}-", 255),
            "location": make_long_text(f"location-{index}-", 255),
            "description": make_long_text(f"description-{index}-", 2000),
            "category": "activity" if index % 2 == 0 else "meal",
            "notes": make_long_text(f"notes-{index}-", 2000),
        }


def test_prompt_budgeting_handles_worst_case_valid_data(database_api) -> None:
    add_maximal_context_items(database_api)
    ollama_api = FakeOllamaProviderApi()
    request_payload = {
        "requested_date": "2027-04-02",
        "goal": make_long_text("goal-", 800),
        "interests": make_long_text("interests-", 1000),
        "constraints": make_long_text("constraints-", 1000),
    }

    with integrated_client(
        database_api=database_api,
        ollama_api=ollama_api,
        backend_settings=student_settings(ai_max_context_items=12),
        shared_service_settings=shared_settings(max_prompt_chars=12000),
    ) as (client, transport):
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json=request_payload,
        )

    assert response.status_code == 200
    assert transport.request_count == 1
    assert transport.paths == ["/generate"]
    assert len(ollama_api.generate_requests) == 1

    prompt = str(ollama_api.generate_requests[0]["prompt"])
    prompt_context = extract_prompt_context(prompt)
    assert len(prompt) <= 12000
    assert prompt_context["requested_date"] == "2027-04-02"
    assert prompt_context["goal"] == request_payload["goal"]
    assert prompt_context["total_existing_items"] == 12
    assert "budget_adjustments" in prompt_context
    assert prompt_context["budget_adjustments"]["item_notes"] >= 1
    assert prompt_context["budget_adjustments"]["item_descriptions"] >= 1


def test_cross_service_context_limits_and_budget_preserve_itinerary_priority(
    database_api,
) -> None:
    trip = trip_record(database_api)
    request = AiSuggestionRequest(
        requested_date="2027-04-02",
        goal="Keep selected cross-service plans in view.",
    )
    long_label = make_long_text("external-", 170)
    accommodation_records = [
        TripAccommodationRecord(
            trip_id=trip.id,
            accommodation_id=f"acc_budget_{index:02d}",
            date="2027-04-01",
            check_out="2027-04-03",
        )
        for index in range(10)
    ]
    activity_records = [
        TripActivityRecord(
            trip_id=trip.id,
            activity_id=f"activity_budget_{index:02d}",
            date="2027-04-02",
            start_time="12:00",
        )
        for index in range(10)
    ]
    transport_records = [
        TripTransportRecord(
            trip_id=trip.id,
            transport_id=f"transport_budget_{index:02d}",
            traveller_count=2,
            plan_status="confirmed",
            added_on="2027-04-01",
        )
        for index in range(10)
    ]
    enriched_accommodations = [
        TripAccommodationDetail(
            **record.model_dump(mode="json"),
            name=long_label,
        )
        for record in accommodation_records
    ]
    enriched_activities = [
        TripActivityDetail(
            **record.model_dump(mode="json"),
            name=long_label,
            price="10.00",
            pricing_basis="PER_PERSON",
            duration_minutes=60,
        )
        for record in activity_records
    ]
    enriched_transport = [
        TripTransportDetail(
            **record.model_dump(mode="json"),
            type="train",
            provider=long_label,
            origin=long_label,
            destination=long_label,
            departure_time="2027-04-02T10:00:00",
            arrival_time="2027-04-02T11:00:00",
            duration_minutes=60,
            price=10,
            pricing_basis="per_traveller",
            estimated_cost=20,
        )
        for record in transport_records
    ]
    settings = student_settings(
        ai_mode_max_prompt_chars=5000,
        ai_max_context_items=12,
        ai_max_context_accommodations=10,
        ai_max_context_activities=10,
        ai_max_context_transport=10,
    )
    selection = select_cross_service_records(
        accommodations=accommodation_records,
        activities=activity_records,
        transport=transport_records,
        request=request,
        settings=settings,
    )
    cross_service_context = prepare_cross_service_prompt_context(
        selection=selection,
        enriched_accommodations=enriched_accommodations,
        accommodation_sources={
            record.accommodation_id: {"location": long_label}
            for record in accommodation_records
        },
        enriched_activities=enriched_activities,
        enriched_transport=enriched_transport,
    )
    context = build_prompt_context(
        trip,
        trip_items(database_api),
        request,
        settings,
        cross_service_context,
    )

    prepared = build_budgeted_prompt(
        prompt_asset=settings.ai_prompt_asset,
        prompt_context=context,
        output_schema=AiModeSuggestionEnvelope.model_json_schema(),
        max_prompt_chars=5000,
    )

    assert len(prepared.prompt) <= 5000
    assert prepared.prompt_context.existing_items
    adjustments = prepared.prompt_context.budget_adjustments
    assert adjustments is not None
    assert adjustments.dropped_transport == 10
    assert adjustments.dropped_accommodations == 10
    assert adjustments.dropped_activities
    assert prepared.prompt_context.omitted_selected_transport == 10
    assert prepared.prompt_context.omitted_selected_accommodations == 10


def test_prompt_budgeting_supports_exact_shared_boundary(database_api) -> None:
    database_api.items = {}
    request_payload = {
        "requested_date": "2027-04-02",
        "goal": "Plan a compact exact-boundary suggestion test.",
    }
    boundary = 12000
    final_prompt_length = None

    for _ in range(3):
        ollama_api = FakeOllamaProviderApi()
        with integrated_client(
            database_api=database_api,
            ollama_api=ollama_api,
            backend_settings=student_settings(ai_mode_max_prompt_chars=boundary),
            shared_service_settings=shared_settings(max_prompt_chars=boundary),
        ) as (client, _):
            response = client.post(
                "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
                json=request_payload,
            )

        assert response.status_code == 200
        assert len(ollama_api.generate_requests) == 1
        final_prompt_length = len(str(ollama_api.generate_requests[0]["prompt"]))
        if final_prompt_length == boundary:
            break
        boundary = final_prompt_length

    assert final_prompt_length == boundary


def test_prompt_budgeting_trims_optional_fields_before_shared_call(
    database_api,
) -> None:
    add_maximal_context_items(database_api)
    ollama_api = FakeOllamaProviderApi()
    request_payload = {
        "requested_date": "2027-04-02",
        "goal": "Retain the goal and requested day.",
        "interests": make_long_text("interests-", 1000),
        "constraints": make_long_text("constraints-", 1000),
    }
    trim_request = AiSuggestionRequest.model_validate(request_payload)
    trim_limit = None
    for candidate_limit in range(1800, 6001):
        try:
            prepared = build_budgeted_prompt(
                prompt_asset=student_settings().ai_prompt_asset,
                prompt_context=build_prompt_context(
                    trip_record(database_api),
                    trip_items(database_api),
                    trim_request,
                    student_settings(ai_max_context_items=12),
                ),
                output_schema=AiModeSuggestionEnvelope.model_json_schema(),
                max_prompt_chars=candidate_limit,
            )
        except ApiError:
            continue
        adjustments = prepared.prompt_context.budget_adjustments
        if adjustments and adjustments.interests:
            trim_limit = len(prepared.prompt)
            break

    assert trim_limit is not None

    with integrated_client(
        database_api=database_api,
        ollama_api=ollama_api,
        backend_settings=student_settings(
            ai_max_context_items=12,
            ai_mode_max_prompt_chars=trim_limit,
        ),
        shared_service_settings=shared_settings(max_prompt_chars=trim_limit),
    ) as (client, transport):
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json=request_payload,
        )

    assert response.status_code == 200
    assert transport.request_count == 1
    prompt_context = extract_prompt_context(
        str(ollama_api.generate_requests[0]["prompt"])
    )
    assert prompt_context["goal"] == request_payload["goal"]
    assert prompt_context["requested_date"] == "2027-04-02"
    assert "budget_adjustments" in prompt_context
    assert prompt_context["budget_adjustments"]["interests"] is True
    assert prompt_context["constraints"] == request_payload["constraints"]
    assert "interests" not in prompt_context


def test_irreducible_prompt_context_fails_before_shared_service_call(
    database_api,
) -> None:
    ollama_api = FakeOllamaProviderApi()
    request_payload = {
        "requested_date": "2027-04-02",
        "goal": make_long_text("goal-", 800),
    }

    with integrated_client(
        database_api=database_api,
        ollama_api=ollama_api,
        backend_settings=student_settings(ai_mode_max_prompt_chars=200),
        shared_service_settings=shared_settings(max_prompt_chars=200),
    ) as (client, transport):
        response = client.post(
            "/api/trips/trip_2027_sydney_getaway/ai-suggestions",
            json=request_payload,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"] == [
        {
            "field": "ai_suggestions",
            "issue": (
                "required trip context exceeds the configured AI prompt budget "
                "of 200 characters"
            ),
        }
    ]
    assert transport.request_count == 0
    assert ollama_api.generate_requests == []
