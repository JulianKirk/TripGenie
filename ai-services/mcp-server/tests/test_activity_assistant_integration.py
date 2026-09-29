"""Actual UI/backend/MCP protocol flow with deterministic external transports."""

import asyncio
import json

import httpx
import pytest

pytest.importorskip("ai_mode_service")
from ai_mode_service.app import create_app as ai_app
from ai_mode_service.config import Settings as AiSettings

pytest.importorskip("student4_backend_service")
pytest.importorskip("student4_frontend_service")
from student4_backend_service.app import create_app as backend_app
from student4_backend_service.config import Settings as BackendSettings
from student4_frontend_service.app import create_app as frontend_app
from student4_frontend_service.config import Settings as FrontendSettings

from tripgenie_mcp.config import Settings
from tripgenie_mcp.provider import ProviderClient
from tripgenie_mcp.server import create_app, create_server

ACTIVITY = "0f2b1c4e-aaaa-bbbb-cccc-000000000004"
DETAIL = {
    "id": ACTIVITY,
    "name": "Real catalogue walk",
    "description": "A catalogue record, not a generated card",
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


@pytest.mark.parametrize("needs_details", [False, True])
def test_frontend_backend_real_mcp_session_and_card_resolution(needs_details):
    provider_calls = []
    model_calls = []
    database_calls = []

    def database_response(request):
        database_calls.append(request)
        assert request.method == "GET"
        assert request.url.path == f"/internal/activity/{ACTIVITY}"
        return httpx.Response(
            200,
            json={
                **DETAIL,
                "price": "46.00",
                "location_details": {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "country_id": "11111111-1111-1111-1111-111111111111",
                    "city_id": "22222222-2222-2222-2222-222222222222",
                },
            },
        )

    def location_response(request):
        if request.url.path == "/location/country":
            return httpx.Response(
                200,
                json={
                    "countries": [
                        {
                            "id": "11111111-1111-1111-1111-111111111111",
                            "name": "australia",
                        }
                    ],
                    "total": 1,
                },
            )
        assert request.url.path == "/location/city"
        return httpx.Response(
            200,
            json={
                "cities": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "name": "sydney",
                        "country_id": "11111111-1111-1111-1111-111111111111",
                    }
                ],
                "total": 1,
            },
        )

    def provider_response(request):
        provider_calls.append(request)
        if request.method == "QUERY":
            summary = {
                key: value
                for key, value in DETAIL.items()
                if key != "availability_schedules"
            }
            return httpx.Response(200, json={"activities": [summary], "total": 1})
        assert request.method == "GET"
        assert request.url.path == f"/activity/{ACTIVITY}"
        return httpx.Response(200, json=DETAIL)

    def model_response(request):
        model_calls.append(json.loads(request.content))
        if len(model_calls) == 1:
            action = {
                "type": "tool",
                "name": "activities_search",
                "arguments": {"filters": {"price": {"max": "50.00"}}, "limit": 6},
            }
        elif needs_details and len(model_calls) == 2:
            action = {
                "type": "tool",
                "name": "activities_get",
                "arguments": {"activity_id": ACTIVITY},
            }
        else:
            action = {
                "type": "final",
                "parts": [
                    {"type": "text", "text": "Here is a match."},
                    {"type": "activity", "activity_id": ACTIVITY},
                ],
            }
        if action["type"] == "tool":
            msg = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": action["name"],
                            "arguments": action["arguments"],
                        }
                    }
                ],
            }
        else:
            msg = {"role": "assistant", "content": json.dumps(action)}
        return httpx.Response(
            200, json={"model": "llama3.1:8b", "done": True, "message": msg}
        )

    async def scenario():
        provider = ProviderClient(
            {"student-4": "http://activity.test"},
            httpx.MockTransport(provider_response),
        )
        mcp = create_app(create_server(Settings(), provider))
        ai = ai_app(
            AiSettings(mcp_url="http://localhost:8012/mcp"),
            ollama_transport=httpx.MockTransport(model_response),
            mcp_transport=httpx.ASGITransport(mcp),
        )
        backend = backend_app(
            BackendSettings(
                assistant_enabled=True,
                ai_mode_url="http://ai.test",
            ),
            database_transport=httpx.MockTransport(database_response),
            location_transport=httpx.MockTransport(location_response),
            ai_mode_transport=httpx.ASGITransport(ai),
        )
        frontend = frontend_app(
            FrontendSettings(backend_url="http://backend.test"),
            transport=httpx.ASGITransport(backend),
        )
        async with (
            mcp.router.lifespan_context(mcp),
            ai.router.lifespan_context(ai),
            backend.router.lifespan_context(backend),
            frontend.router.lifespan_context(frontend),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(frontend), base_url="http://frontend.test"
            ) as client,
        ):
            response = await client.post(
                "/suggestions/ask",
                data={"question": "Walks below $50"},
                headers={"HX-Request": "true"},
            )
            assert response.status_code == 200
            assert "Real catalogue walk" in response.text, response.text
            assert "Tools used" in response.text
            assert "activities_search" in response.text
            assert ("activities_get" in response.text) is needs_details
            assert "$46.00" in response.text
            assert "Add to itinerary" in response.text
        provider.close()

    asyncio.run(scenario())
    assert len(model_calls) == (4 if needs_details else 3)
    assert len(database_calls) == 1
    assert "activities_create" in json.dumps(model_calls[0]["tools"])
    assert model_calls[-1]["format"]["type"] == "object"
    assert [request.method for request in provider_calls] == (
        ["QUERY", "GET"] if needs_details else ["QUERY"]
    )
    assert json.loads(provider_calls[0].content)["price"] == {"max": "50.00"}
    correlation = provider_calls[0].headers["X-Request-ID"]
    assert correlation.startswith("student4-agent-")
    assert all(
        request.headers["X-Request-ID"] == correlation for request in provider_calls
    )
