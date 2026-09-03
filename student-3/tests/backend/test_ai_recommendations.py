"""AI transport recommendations.

The model is advisory: these tests pin the guards that stop a generated reply
being presented as if it were TripGenie data — the candidate list is bounded,
an invented identifier is rejected, and nothing on this path writes.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from conftest import (
    make_ai_error_transport,
    make_ai_transport,
    make_ai_unreachable_transport,
)
from fastapi.testclient import TestClient
from student3_backend_service.app import create_app
from student3_backend_service.config import Settings

RECOMMEND_PATH = "/api/transport-options/recommendations"
ENTRIES_PATH = "/api/transport-bookings"

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


def ai_reply(draft: dict[str, Any], *, done: bool = True) -> httpx.Response:
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
            },
        },
    )


@contextmanager
def build_client(
    database_transport: httpx.MockTransport,
    ai_transport: httpx.BaseTransport | None,
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
    )
    with TestClient(app) as client:
        yield client


@contextmanager
def capturing_client(
    database_transport: httpx.MockTransport,
    draft: dict[str, Any],
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
def ai_client(database_transport: httpx.MockTransport) -> Iterator[TestClient]:
    with build_client(database_transport, make_ai_transport(GOOD_DRAFT)) as client:
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
    assert body["recommended"][0]["option"]["price"] == 6.50
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


def test_recommendation_resolves_ids_to_real_records(ai_client: TestClient) -> None:
    """A suggestion comes back as the full option, not just an id.

    The frontend must never have to trust an id it cannot render.
    """
    body = _data(ai_client.post(RECOMMEND_PATH, json=ASK))
    option = body["recommended"][0]["option"]

    for field in ("id", "duration_minutes", "seats_remaining", "availability_status"):
        assert field in option


# ------------------------------------------------------------------ no writes


def test_recommending_does_not_create_a_plan_entry(ai_client: TestClient) -> None:
    """Nothing on the AI path may persist. The traveller saves, not the model."""
    before = len(_data(ai_client.get(ENTRIES_PATH)))

    assert ai_client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    assert len(_data(ai_client.get(ENTRIES_PATH))) == before


# ------------------------------------------------------------------ grounding


def test_an_invented_transport_id_is_rejected(
    database_transport: httpx.MockTransport,
) -> None:
    """A hallucinated id must never reach a traveller.

    Resolving suggestions against the candidate list is the guard; without it a
    made-up id would render as a broken link or an empty row.
    """
    draft = {
        **GOOD_DRAFT,
        "suggestions": [
            {
                "transport_id": "transport_does_not_exist",
                "reason": "Invented by the model.",
            },
        ],
    }
    with build_client(database_transport, make_ai_transport(draft)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert _error(response)["code"] == "BAD_GATEWAY"
    assert "unknown transport id" in _error(response)["details"][0]["issue"]


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
    with build_client(database_transport, make_ai_transport(draft)) as client:
        body = _data(client.post(RECOMMEND_PATH, json=ASK))

    assert len(body["recommended"]) == 1
    assert body["recommended"][0]["reason"] == "Cheapest."


@pytest.mark.parametrize("excluded", [SOLD_OUT_ID, CANCELLED_ID])
def test_unbookable_options_are_never_candidates(
    database_transport: httpx.MockTransport,
    excluded: str,
) -> None:
    """The model can only pick from what it is shown.

    Naming an option that was filtered out therefore fails the same guard as an
    invented id, which is the cheapest way to enforce the rule.
    """
    draft = {
        **GOOD_DRAFT,
        "suggestions": [{"transport_id": excluded, "reason": "Should not be."}],
    }
    with build_client(database_transport, make_ai_transport(draft)) as client:
        response = client.post(RECOMMEND_PATH, json=ASK)

    assert response.status_code == 502
    assert excluded in _error(response)["details"][0]["issue"]


def test_the_prompt_grounds_the_model_in_candidate_ids(
    database_transport: httpx.MockTransport,
) -> None:
    """Capture the outbound prompt and assert the grounding is real."""
    with capturing_client(database_transport, GOOD_DRAFT) as (client, captured):
        assert client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    prompt = captured["prompt"]
    assert "Only these transport ids may be recommended:" in prompt
    assert CHEAPEST_ID in prompt
    # Unbookable options are not even offered.
    assert SOLD_OUT_ID not in prompt
    assert CANCELLED_ID not in prompt
    # The schema goes with the call so the provider returns the shape we parse.
    assert "suggestions" in json.dumps(captured["schema"])
    assert captured["correlation_id"].startswith("student3-transport-")
    assert captured["metadata"]["feature"] == "transport-recommendations"


def test_the_candidate_list_is_capped(
    database_transport: httpx.MockTransport,
) -> None:
    """A bounded prompt is what keeps the request inside AI-Mode's limits."""
    with capturing_client(
        database_transport,
        GOOD_DRAFT,
        ai_max_candidates=2,
    ) as (client, captured):
        assert client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    assert captured["metadata"]["candidates"] == "2"
    # The key-facts block lists exactly the ids the model may name.
    allowed = captured["prompt"].split(
        "Only these transport ids may be recommended: ",
    )[1].splitlines()[0]
    assert len(allowed.split(", ")) == 2


def test_the_prompt_states_the_currency(
    database_transport: httpx.MockTransport,
) -> None:
    """Prices mean nothing without it, and Student 5 consumes the same figure."""
    with capturing_client(database_transport, GOOD_DRAFT) as (client, captured):
        assert client.post(RECOMMEND_PATH, json=ASK).status_code == 200

    assert "Currency: AUD" in captured["prompt"]


def test_a_trip_adds_its_existing_plan_to_the_context(
    database_transport: httpx.MockTransport,
) -> None:
    with capturing_client(database_transport, GOOD_DRAFT) as (client, captured):
        response = client.post(
            RECOMMEND_PATH,
            json=ASK | {"trip_id": "trip_2026_sydney_long_weekend"},
        )
        assert response.status_code == 200, response.text

    assert "trip_2026_sydney_long_weekend" in captured["prompt"]
    assert "already_planned" in captured["prompt"]
    assert FLIGHT_ID in captured["prompt"]


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
    """Better to say so plainly than to ask the model about an empty list."""
    response = ai_client.post(
        RECOMMEND_PATH,
        json=ASK | {"origin": "Nowhere", "destination": "Neverland"},
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_ERROR"
    assert "no available option" in _error(response)["details"][0]["issue"]


def test_a_route_filter_narrows_the_candidates(
    database_transport: httpx.MockTransport,
) -> None:
    draft = {
        **GOOD_DRAFT,
        "suggestions": [
            {"transport_id": "transport_2027_jl772_syd_hnd", "reason": "Only option."},
        ],
    }
    with capturing_client(database_transport, draft) as (client, captured):
        response = client.post(
            RECOMMEND_PATH,
            json=ASK | {"origin": "Sydney", "destination": "Tokyo"},
        )
        assert response.status_code == 200, response.text

    assert captured["metadata"]["candidates"] == "1"
    assert CHEAPEST_ID not in captured["prompt"]
