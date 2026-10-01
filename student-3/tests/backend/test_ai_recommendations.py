"""AI transport recommendations, model-directed through the shared MCP tools.

The model is advisory: these tests pin the guards that stop a generated reply
being presented as if it were TripGenie data. The model must look transport up
itself through AI-Mode's MCP tool loop, a suggestion is accepted only when a
successful transport tool returned it, each one is re-read from this service,
and nothing on this path writes.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from conftest import (
    FakeItineraryApi,
    make_ai_error_transport,
    make_ai_unreachable_transport,
)
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

RECOMMEND_PATH = "/api/transport-options/recommendations"

FLIGHT_ID = "transport_2026_qf401_mel_syd"
SOLD_OUT_ID = "transport_2026_sq232_syd_sin"
CANCELLED_ID = "transport_2027_xpt_syd_bne"
CHEAPEST_ID = "transport_2027_adl_metro_bus"

ASK: dict[str, Any] = {"question": "What is the cheapest way to get around?"}

GOOD_DRAFT: dict[str, Any] = {
    "overview": "The Adelaide airport bus at $6.50 per traveller is the cheapest.",
    "suggestions": [
        {
            "transport_id": CHEAPEST_ID,
            "reason": "Cheapest at $6.50 per traveller and only 35m.",
        },
    ],
    "considerations": ["Fares are tapped on board."],
    "disclaimer": "Advisory only. Review before adding to your trip.",
}


def tool_trace(
    tool: str,
    data: dict[str, Any],
    *,
    status: str = "success",
    source: str = "student-3",
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One entry of AI-Mode's `tools` trace, shaped as AI-Mode reports it."""
    return {
        "tool": tool,
        "arguments": arguments if arguments is not None else {"limit": 12},
        "status": status,
        "duration_ms": 31,
        "result": {
            "content": [],
            "structuredContent": {
                "ok": status == "success",
                "data": data,
                "correlation_id": "mcp-test",
                "source": source,
            },
            "isError": status != "success",
        },
        "error": None if status == "success" else "tool failed",
    }


def search_trace(*ids: str, **kwargs: Any) -> dict[str, Any]:
    items = [{"id": transport_id, "price": "6.50"} for transport_id in ids]
    return tool_trace(
        "transport_search",
        {"items": items, "count": len(items), "truncated": False},
        **kwargs,
    )


SEARCH_CHEAPEST = search_trace(CHEAPEST_ID)


def ai_reply(
    draft: dict[str, Any],
    tools: list[dict[str, Any]] | None = None,
    *,
    done: bool = True,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "run_id": "run_test_0001",
                "correlation_id": "student3-transport-test",
                "model": "llama3.1:8b",
                "provider": "ollama",
                "response": json.dumps(draft),
                "done": done,
                "tools": [SEARCH_CHEAPEST] if tools is None else tools,
            },
        },
    )


def reply_with(
    draft: dict[str, Any],
    tools: list[dict[str, Any]] | None = None,
) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _request: ai_reply(draft, tools))


@contextmanager
def build_client(
    database_transport: httpx.MockTransport,
    ai_transport: httpx.BaseTransport | None,
    itinerary_transport: httpx.BaseTransport | None = None,
    **overrides: Any,
) -> Iterator[TestClient]:
    """A backend wired to a stubbed AI-Mode.

    A context manager rather than a bare generator: the TestClient has to stay
    entered for the whole test, and a generator dropped after a single next()
    closes its client straight away.
    """
    settings = Settings(
        database_api_base_url="http://student-3-database:8004",
        **overrides,
    )
    app = create_app(
        settings,
        transport=database_transport,
        ai_transport=ai_transport,
        trips_transport=itinerary_transport,
    )
    with TestClient(app) as client:
        yield client


@contextmanager
def capturing_client(
    database_transport: httpx.MockTransport,
    draft: dict[str, Any] = GOOD_DRAFT,
    **overrides: Any,
) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    """A client that records the request body sent to AI-Mode."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return ai_reply(draft)

    with build_client(
        database_transport,
        httpx.MockTransport(handler),
        **overrides,
    ) as client:
        yield client, captured


@pytest.fixture
def ai_client(
    database_transport: httpx.MockTransport,
    itinerary_transport: httpx.MockTransport,
) -> Iterator[TestClient]:
    with build_client(
        database_transport,
        reply_with(GOOD_DRAFT),
        itinerary_transport,
    ) as client:
        yield client


def _data(response) -> Any:
    return response.json()["data"]


def _error(response) -> dict[str, Any]:
    return response.json()["error"]


# ----------------------------------------------------------------- happy path


def test_recommendation_returns_a_resolved_draft(ai_client: TestClient) -> None:
    response = ai_client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 200, response.text
    body = _data(response)
    assert body["overview"].startswith("The Adelaide airport bus")
    assert len(body["recommended"]) == 1
    assert body["recommended"][0]["option"]["id"] == CHEAPEST_ID
    assert body["considerations"] == ["Fares are tapped on board."]


def test_recommendation_reports_its_provenance(ai_client: TestClient) -> None:
    body = _data(ai_client.post(RECOMMEND_PATH, json=ASK))

    assert body["run_id"] == "run_test_0001"
    assert body["model"] == "llama3.1:8b"
    assert body["provider"] == "ollama"


def test_recommendation_is_marked_advisory(ai_client: TestClient) -> None:
    """The flag exists so a consumer cannot mistake advice for stored data."""
    body = _data(ai_client.post(RECOMMEND_PATH, json=ASK))

    assert body["advisory_only"] is True
    assert body["disclaimer"]


def test_suggestions_are_the_stored_records_not_the_tool_copy(
    ai_client: TestClient,
) -> None:
    """The tool said $6.50 as text; the response carries the stored record.

    The frontend must never have to trust a figure only the model or a tool
    result produced.
    """
    option = _data(ai_client.post(RECOMMEND_PATH, json=ASK))["recommended"][0]["option"]

    assert option["price"] == 6.50
    for field in ("id", "duration_minutes", "seats_remaining", "availability_status"):
        assert field in option


def test_the_tool_calls_are_returned_as_evidence(ai_client: TestClient) -> None:
    (trace,) = _data(ai_client.post(RECOMMEND_PATH, json=ASK))["tools"]

    assert trace["tool"] == "transport_search"
    assert trace["status"] == "success"
    assert trace["arguments"] == {"limit": 12}
    assert trace["duration_ms"] == 31
    assert trace["transport_ids"] == [CHEAPEST_ID]
    assert trace["result"]["source"] == "student-3"
    assert trace["result"]["data"]["count"] == 1


# ------------------------------------------------------------------ no writes


def test_recommending_does_not_select_anything(
    ai_client: TestClient,
    itinerary_api: FakeItineraryApi,
) -> None:
    """Nothing on the AI path may persist. The traveller chooses, not the model.

    Asserted against the itinerary service's own state, because that is where a
    selection would have to land for it to exist at all.
    """
    assert itinerary_api.pins == {}

    assert ai_client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    assert itinerary_api.pins == {}


# ------------------------------------------------------------------ grounding


def test_an_invented_transport_id_is_rejected(
    database_transport: httpx.MockTransport,
) -> None:
    """A hallucinated id must never reach a traveller."""
    draft = {
        **GOOD_DRAFT,
        "suggestions": [
            {"transport_id": "transport_does_not_exist", "reason": "Invented."},
        ],
    }
    with build_client(database_transport, reply_with(draft)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert _error(response)["code"] == "BAD_GATEWAY"
    assert "ungrounded transport id" in _error(response)["details"][0]["issue"]


def test_a_real_id_the_model_never_looked_up_is_rejected(
    database_transport: httpx.MockTransport,
) -> None:
    """Existing in the catalogue is not enough: a tool must have returned it.

    Otherwise the model could recite an id from training data or the prompt
    and skip the lookup the traveller is being shown.
    """
    draft = {
        **GOOD_DRAFT,
        "suggestions": [{"transport_id": FLIGHT_ID, "reason": "Real but unseen."}],
    }
    with build_client(database_transport, reply_with(draft)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert FLIGHT_ID in _error(response)["details"][0]["issue"]


@pytest.mark.parametrize(
    "trace",
    [
        search_trace(CHEAPEST_ID, status="error"),
        search_trace(CHEAPEST_ID, source="student-4"),
        tool_trace("transport_search", {"unexpected": [CHEAPEST_ID]}),
    ],
    ids=["failed-call", "other-service", "unrecognised-shape"],
)
def test_only_successful_student_3_tool_results_ground_an_id(
    database_transport: httpx.MockTransport,
    trace: dict[str, Any],
) -> None:
    with build_client(database_transport, reply_with(GOOD_DRAFT, [trace])) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502


def test_no_tool_calls_means_no_grounded_suggestion(
    database_transport: httpx.MockTransport,
) -> None:
    with build_client(database_transport, reply_with(GOOD_DRAFT, [])) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert "ungrounded" in _error(response)["details"][0]["issue"]


@pytest.mark.parametrize(
    "trace",
    [
        tool_trace("transport_get", {"id": CHEAPEST_ID, "price": "6.50"}),
        tool_trace(
            "transport_trip_costs",
            {
                "trip_id": "trip_2026_sydney_long_weekend",
                "planned": [{"option": {"id": CHEAPEST_ID}, "entry": {}}],
            },
        ),
        tool_trace("transport_compare", {"items": [{"id": CHEAPEST_ID}]}),
    ],
    ids=["get", "trip-costs", "compare"],
)
def test_every_transport_tool_can_ground_an_id(
    database_transport: httpx.MockTransport,
    trace: dict[str, Any],
) -> None:
    with build_client(database_transport, reply_with(GOOD_DRAFT, [trace])) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 200, response.text
    assert _data(response)["recommended"][0]["option"]["id"] == CHEAPEST_ID


def test_a_duplicate_suggestion_is_collapsed(
    database_transport: httpx.MockTransport,
) -> None:
    """Repetition is noise, not a failure, so the first mention wins."""
    draft = {
        **GOOD_DRAFT,
        "suggestions": [
            {"transport_id": CHEAPEST_ID, "reason": "Cheapest."},
            {"transport_id": CHEAPEST_ID, "reason": "Still cheap."},
        ],
    }
    with build_client(database_transport, reply_with(draft)) as client:
        body = _data(client.post(RECOMMEND_PATH, json=ASK))

    assert len(body["recommended"]) == 1
    assert body["recommended"][0]["reason"] == "Cheapest."


@pytest.mark.parametrize("excluded", [SOLD_OUT_ID, CANCELLED_ID])
def test_an_unbookable_option_a_tool_returned_is_named_not_shown(
    database_transport: httpx.MockTransport,
    excluded: str,
) -> None:
    """A tool may return a sold-out option; the traveller must not be sold it."""
    draft = {
        **GOOD_DRAFT,
        "suggestions": [
            {"transport_id": excluded, "reason": "Should not be shown."},
            {"transport_id": CHEAPEST_ID, "reason": "Cheapest."},
        ],
    }
    tools = [search_trace(excluded, CHEAPEST_ID)]
    with build_client(database_transport, reply_with(draft, tools)) as client:
        body = _data(client.post(RECOMMEND_PATH, json=ASK))

    assert [item["option"]["id"] for item in body["recommended"]] == [CHEAPEST_ID]
    assert body["unavailable_transport_ids"] == [excluded]


def test_only_unbookable_suggestions_is_a_bad_gateway(
    database_transport: httpx.MockTransport,
) -> None:
    draft = {
        **GOOD_DRAFT,
        "suggestions": [{"transport_id": SOLD_OUT_ID, "reason": "Sold out."}],
    }
    tools = [search_trace(SOLD_OUT_ID)]
    with build_client(database_transport, reply_with(draft, tools)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert "no suggestions could be resolved" in _error(response)["details"][0]["issue"]


def test_a_grounded_option_since_deleted_is_named_not_shown(
    database_transport: httpx.MockTransport,
) -> None:
    gone = "transport_gone_since_search"
    draft = {
        **GOOD_DRAFT,
        "suggestions": [
            {"transport_id": gone, "reason": "Was there a moment ago."},
            {"transport_id": CHEAPEST_ID, "reason": "Cheapest."},
        ],
    }
    tools = [search_trace(gone, CHEAPEST_ID)]
    with build_client(database_transport, reply_with(draft, tools)) as client:
        body = _data(client.post(RECOMMEND_PATH, json=ASK))

    assert body["unavailable_transport_ids"] == [gone]
    assert len(body["recommended"]) == 1


# --------------------------------------------------------------------- prompt


def test_the_model_is_told_to_use_the_tools_not_given_a_list(
    database_transport: httpx.MockTransport,
) -> None:
    """Nothing from the catalogue is pre-loaded: the model has to fetch it."""
    with capturing_client(database_transport) as (client, captured):
        assert client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    system = captured["system"]
    assert "transport_search" in system
    assert "transport_trip_costs" in system
    assert "Never invent, alter or guess an id" in system
    assert "are in AUD" in system
    # No transport records travel in the request any more.
    request_text = system + captured["prompt"]
    for transport_id in (CHEAPEST_ID, FLIGHT_ID, SOLD_OUT_ID):
        assert transport_id not in request_text
    assert json.loads(captured["prompt"]) == ASK | {"first_search": {"limit": 12}}
    # The schema goes with the call so the provider returns the shape we parse.
    assert "suggestions" in json.dumps(captured["schema"])
    assert captured["correlation_id"].startswith("student3-transport-")
    assert captured["metadata"]["feature"] == "transport-recommendations"


def test_the_request_fields_are_passed_as_data(
    database_transport: httpx.MockTransport,
) -> None:
    ask = ASK | {
        "origin": "Sydney",
        "destination": "Tokyo",
        "trip_id": "trip_2026_sydney_long_weekend",
    }
    with capturing_client(database_transport) as (client, captured):
        assert client.post(RECOMMEND_PATH, json=ask).status_code == 200

    assert json.loads(captured["prompt"]) == {
        "question": ASK["question"],
        "first_search": {"limit": 12, "origin": "Sydney", "destination": "Tokyo"},
        "trip_id": "trip_2026_sydney_long_weekend",
    }


def test_the_search_limit_never_exceeds_the_mcp_maximum(
    database_transport: httpx.MockTransport,
) -> None:
    with capturing_client(database_transport, ai_max_candidates=80) as (
        client,
        captured,
    ):
        assert client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    assert json.loads(captured["prompt"])["first_search"]["limit"] == 50


def test_an_oversized_prompt_is_refused_before_ai_mode(
    database_transport: httpx.MockTransport,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return ai_reply(GOOD_DRAFT)

    with build_client(
        database_transport,
        httpx.MockTransport(handler),
        ai_prompt_max_chars=200,
    ) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 422
    assert _error(response)["code"] == "PROMPT_BUDGET_EXCEEDED"
    assert calls == []


def test_tool_calls_are_logged_without_their_data(
    ai_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="student3_backend_service.service"):
        ai_client.post(RECOMMEND_PATH, json=ASK)

    assert "tool_calls=transport_search:success" in caplog.text
    assert "6.50" not in caplog.text


# ----------------------------------------------------------- dependency faults


def test_a_malformed_ai_reply_is_a_bad_gateway(
    database_transport: httpx.MockTransport,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "r",
                    "correlation_id": "c",
                    "model": "m",
                    "provider": "ollama",
                    "response": "this is not json",
                    "done": True,
                },
            },
        )

    with build_client(database_transport, httpx.MockTransport(handler)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert "schema" in _error(response)["details"][0]["issue"]


def test_an_unfinished_generation_is_rejected(
    database_transport: httpx.MockTransport,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ai_reply(GOOD_DRAFT, done=False)

    with build_client(database_transport, httpx.MockTransport(handler)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert "incomplete" in _error(response)["details"][0]["issue"]


def test_an_unreachable_ai_mode_is_a_503(
    database_transport: httpx.MockTransport,
) -> None:
    with build_client(database_transport, make_ai_unreachable_transport()) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 503
    assert _error(response)["code"] == "DEPENDENCY_UNAVAILABLE"


def test_ai_mode_unavailability_is_passed_through(
    database_transport: httpx.MockTransport,
) -> None:
    """AI-Mode's own 503 stays a 503: it is the same class of problem."""
    transport = make_ai_error_transport(503, "OLLAMA_UNAVAILABLE")
    with build_client(database_transport, transport) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 503
    assert _error(response)["code"] == "OLLAMA_UNAVAILABLE"


def test_an_ai_mode_rejection_becomes_a_bad_gateway(
    database_transport: httpx.MockTransport,
) -> None:
    """A 422 from AI-Mode is this service's bug, not the traveller's."""
    transport = make_ai_error_transport(422, "VALIDATION_ERROR")
    with build_client(database_transport, transport) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502


# ------------------------------------------------------------------- requests


def test_a_question_is_required(ai_client: TestClient) -> None:
    response = ai_client.post(RECOMMEND_PATH, json={})

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"


def test_an_unknown_field_is_rejected(ai_client: TestClient) -> None:
    response = ai_client.post(RECOMMEND_PATH, json=ASK | {"budget": 100})

    assert response.status_code == 422


def test_a_malformed_trip_id_is_rejected(ai_client: TestClient) -> None:
    response = ai_client.post(RECOMMEND_PATH, json=ASK | {"trip_id": "hobart"})

    assert response.status_code == 422


def test_a_route_with_no_available_option_is_a_validation_error(
    ai_client: TestClient,
) -> None:
    """Better to say so plainly than to spend a model run on an empty route."""
    response = ai_client.post(
        RECOMMEND_PATH,
        json=ASK | {"origin": "Nowhere", "destination": "Neverland"},
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"
    assert "no available option" in _error(response)["details"][0]["issue"]


def test_a_route_of_only_unbookable_options_never_reaches_ai_mode(
    database_transport: httpx.MockTransport,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return ai_reply(GOOD_DRAFT)

    with build_client(database_transport, httpx.MockTransport(handler)) as client:
        # Sydney to Singapore is seeded only as a sold-out flight.
        response = client.post(
            RECOMMEND_PATH,
            json=ASK | {"origin": "Sydney", "destination": "Singapore"},
        )

    assert response.status_code == 422
    assert calls == []


def test_an_empty_draft_is_an_honest_no_match(
    database_transport: httpx.MockTransport,
) -> None:
    """No suggestions means the model found nothing; that is an answer."""
    draft = {**GOOD_DRAFT, "overview": "Nothing suitable was found.", "suggestions": []}
    with build_client(database_transport, reply_with(draft)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 200
    body = _data(response)
    assert body["overview"] == "Nothing suitable was found."
    assert body["recommended"] == []
    assert body["tools"]
