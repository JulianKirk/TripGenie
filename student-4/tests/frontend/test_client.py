from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

import httpx
import pytest
from student4_frontend_service.errors import FrontendError
from student4_frontend_service.models import ActivityWrite, ItinerarySelectionWrite

from tests.frontend.conftest import ACTIVITY_ID, DETAIL, TRIP_ID, FakeBackend

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from student4_frontend_service.client import BackendClient

T = TypeVar("T")


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


def write_model() -> ActivityWrite:
    payload = deepcopy(DETAIL)
    payload.pop("id")
    payload["availability_schedules"][0].pop("id")
    return ActivityWrite.model_validate(payload)


def test_search_uses_query_with_exact_body(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    page = run(backend_client.search({"text": "harbour", "limit": 10, "offset": 0}))

    assert backend.last_request.method == "QUERY"
    assert backend.last_request.url.path == "/activity"
    assert backend.json_body() == {"text": "harbour", "limit": 10, "offset": 0}
    assert page.total == 1
    assert page.activities[0].price.as_tuple().exponent == -2


def test_read_operations_use_only_public_backend_routes(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    health = run(backend_client.health())
    categories = run(backend_client.categories())
    activity = run(backend_client.activity(UUID(ACTIVITY_ID)))

    assert health.status == "ok"
    assert [category.code for category in categories.categories] == ["OUTDOOR", "TOUR"]
    assert activity.name == "Sydney Harbour guided walk"
    assert [request.url.path for request in backend.requests] == [
        "/health",
        "/activity/categories",
        f"/activity/{ACTIVITY_ID}",
    ]


def test_activity_mutations_use_documented_methods_and_payloads(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    body = write_model()
    created = run(backend_client.create_activity(body))
    replaced = run(backend_client.replace_activity(UUID(ACTIVITY_ID), body))
    deleted = run(backend_client.delete_activity(UUID(ACTIVITY_ID)))

    assert created.id == replaced.id == UUID(ACTIVITY_ID)
    assert deleted.deleted is True
    assert [(item.method, item.url.path) for item in backend.requests] == [
        ("POST", "/activity"),
        ("PUT", f"/activity/{ACTIVITY_ID}"),
        ("DELETE", f"/activity/{ACTIVITY_ID}"),
    ]
    assert json.loads(backend.requests[1].content) == {
        "name": "Sydney Harbour guided walk",
        "description": "A guided walk around the harbour foreshore.",
        "price": "45.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
        "minimum_age": 8,
        "minimum_participants": 1,
        "maximum_participants": 12,
        "booking_required": True,
        "booking_notes": "Arrange at least 24 hours ahead.",
        "wheelchair_accessible": False,
        "step_free_access": False,
        "accessible_toilet": True,
        "accessibility_notes": "Some sections contain steep paths.",
        "is_active": True,
        "location_details": {
            "country": "australia",
            "city": "sydney",
            "street": "circular quay",
        },
        "categories": ["OUTDOOR", "TOUR"],
        "availability_schedules": [
            {
                "recurring_weekly": True,
                "day_of_week": "SATURDAY",
                "start_time": "09:00",
                "end_time": "11:00",
            }
        ],
    }


def test_itinerary_operations_stay_on_student_4_backend(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    picker = run(backend_client.itineraries(UUID(ACTIVITY_ID)))
    write = ItinerarySelectionWrite.model_validate(
        {"date": "2027-04-02", "start_time": "09:30"}
    )
    run(backend_client.put_itinerary(UUID(ACTIVITY_ID), TRIP_ID, write))
    run(backend_client.delete_itinerary(UUID(ACTIVITY_ID), TRIP_ID))

    assert picker.itineraries[0].name == "Sydney Getaway"
    assert [(item.method, item.url.path) for item in backend.requests] == [
        ("GET", f"/activity/{ACTIVITY_ID}/itineraries"),
        ("PUT", f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}"),
        ("DELETE", f"/activity/{ACTIVITY_ID}/itineraries/{TRIP_ID}"),
    ]


def test_backend_validation_detail_is_preserved(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    backend.overrides[("QUERY", "/activity")] = httpx.Response(
        400, json={"detail": "city requires country"}
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.search({"limit": 20, "offset": 0}))

    assert raised.value.status_code == 400
    assert raised.value.detail == "city requires country"


def test_structured_backend_validation_detail_is_made_readable(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    backend.overrides[("POST", "/activity")] = httpx.Response(
        400,
        json={
            "detail": [
                {
                    "type": "value_error",
                    "loc": ["body", "maximum_age"],
                    "msg": "Value error, maximum_age must be at least minimum_age",
                    "input": 4,
                }
            ]
        },
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.create_activity(write_model()))

    assert raised.value.detail == (
        "maximum_age: Value error, maximum_age must be at least minimum_age"
    )
    assert "input" not in raised.value.detail


def test_backend_server_error_detail_is_not_exposed(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        500, json={"detail": "database password appeared in a traceback"}
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.activity(UUID(ACTIVITY_ID)))

    assert raised.value.detail == (
        "The activities service is unavailable. Please try again."
    )
    assert "password" not in raised.value.detail


def test_malformed_success_is_reported_safely(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    backend.overrides[("QUERY", "/activity")] = httpx.Response(
        200, json={"activities": "wrong"}
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.search({"limit": 20, "offset": 0}))

    assert raised.value.kind == "malformed_upstream"
    assert raised.value.status_code == 502


def test_success_that_breaks_backend_activity_invariants_is_rejected(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    malformed = deepcopy(DETAIL)
    malformed["availability_schedules"] = []
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        200, json=malformed
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.activity(UUID(ACTIVITY_ID)))

    assert raised.value.kind == "malformed_upstream"


@pytest.mark.parametrize("display_order", [-1, "60"])
def test_malformed_category_order_is_rejected(
    backend_client: BackendClient,
    backend: FakeBackend,
    display_order: object,
) -> None:
    backend.overrides[("GET", "/activity/categories")] = httpx.Response(
        200,
        json={
            "categories": [
                {
                    "code": "OUTDOOR",
                    "label": "Outdoor",
                    "description": None,
                    "display_order": display_order,
                }
            ]
        },
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.categories())

    assert raised.value.kind == "malformed_upstream"


@pytest.mark.parametrize(
    "exception",
    [httpx.ConnectError("offline"), httpx.ReadTimeout("slow")],
)
def test_transport_failures_are_retryable(
    backend_client: BackendClient,
    backend: FakeBackend,
    exception: httpx.RequestError,
) -> None:
    backend.overrides[("GET", "/health")] = exception

    with pytest.raises(FrontendError) as raised:
        run(backend_client.health())

    assert raised.value.kind == "unavailable"
    assert raised.value.status_code == 503


def test_non_json_backend_error_does_not_leak_body(
    backend_client: BackendClient,
    backend: FakeBackend,
) -> None:
    backend.overrides[("GET", f"/activity/{ACTIVITY_ID}")] = httpx.Response(
        503, text="secret proxy dump"
    )

    with pytest.raises(FrontendError) as raised:
        run(backend_client.activity(UUID(ACTIVITY_ID)))

    assert "secret proxy dump" not in raised.value.detail
