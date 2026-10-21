"""Post-commit endpoint tests against the live Student 3 Compose stack.

student-3-ci.yml's compose job runs these over HTTP once the slice is up, so
they exercise the built images rather than in-process apps. The two endpoint
functions under test are creating and reading a transport option, and
comparing transport options. Ordinary pytest runs exclude this directory
through testpaths in pyproject.toml.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

BASE_URL = os.environ.get("STUDENT3_ENDPOINT_BASE_URL", "http://127.0.0.1:18003")
# Seeded by the database service, departing in this order.
QANTAS = "transport_2026_qf401_mel_syd"
TOKYO = "transport_2027_jl772_syd_hnd"


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"{BASE_URL}/api", timeout=10) as http:
        httpx.get(f"{BASE_URL}/ready", timeout=10).raise_for_status()
        yield http


def option_payload(**overrides: object) -> dict[str, Any]:
    return {
        "id": f"transport_ci_{uuid.uuid4().hex[:12]}",
        "type": "bus",
        "provider": "CI Coaches",
        "origin": "Canberra",
        "destination": "Sydney",
        "departure_time": "2027-03-01T08:00",
        "arrival_time": "2027-03-01T11:30",
        "price": 48.75,
        "capacity": 40,
        "availability_status": "available",
    } | overrides


@pytest.fixture
def option(client: httpx.Client) -> Iterator[dict[str, Any]]:
    response = client.post("/transport-options", json=option_payload())
    assert response.status_code == 201, response.text
    created = response.json()["data"]
    yield created
    # Remove it again so reruns against the same stack start clean.
    client.delete(f"/transport-options/{created['id']}")


def detail_fields(response: httpx.Response) -> list[str]:
    return [detail["field"] for detail in response.json()["error"]["details"]]


# ------------------------------------- endpoint 1: create and read an option


def test_a_created_option_is_stored_and_read_back(
    client: httpx.Client,
    option: dict[str, Any],
) -> None:
    response = client.get(f"/transport-options/{option['id']}")

    assert response.status_code == 200, response.text
    stored = response.json()["data"]
    assert stored == option
    assert stored["provider"] == "CI Coaches"
    assert stored["price"] == 48.75
    # Derived by the service, never sent by the caller.
    assert stored["duration_minutes"] == 210
    assert stored["pricing_basis"] == "per_traveller"


def test_a_created_option_appears_in_the_filtered_list(
    client: httpx.Client,
    option: dict[str, Any],
) -> None:
    response = client.get(
        "/transport-options",
        params={"provider": "CI Coaches", "origin": "Canberra"},
    )

    assert response.status_code == 200
    assert option["id"] in [item["id"] for item in response.json()["data"]]


def test_an_option_going_nowhere_is_rejected(client: httpx.Client) -> None:
    response = client.post(
        "/transport-options",
        json=option_payload(origin="Sydney", destination=" sydney "),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert detail_fields(response) == ["destination"]


def test_an_option_arriving_before_it_departs_is_rejected(
    client: httpx.Client,
) -> None:
    response = client.post(
        "/transport-options",
        json=option_payload(arrival_time="2027-03-01T07:00"),
    )

    assert response.status_code == 422


def test_an_unknown_option_is_not_found(client: httpx.Client) -> None:
    response = client.get("/transport-options/transport_ci_missing_option")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ------------------------------------------- endpoint 2: compare options


def test_compare_returns_the_options_in_departure_order(
    client: httpx.Client,
) -> None:
    response = client.get(
        "/transport-options/compare",
        params={"ids": f"{TOKYO},{QANTAS}"},
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["data"]] == [QANTAS, TOKYO]


def test_compare_includes_a_newly_created_option(
    client: httpx.Client,
    option: dict[str, Any],
) -> None:
    response = client.get(
        "/transport-options/compare",
        params={"ids": f"{QANTAS},{option['id']}"},
    )

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["data"]} == {QANTAS, option["id"]}


def test_compare_reports_an_unknown_option(client: httpx.Client) -> None:
    response = client.get(
        "/transport-options/compare",
        params={"ids": f"{QANTAS},transport_ci_missing_option"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "ids",
    [
        ",".join(
            [
                QANTAS,
                TOKYO,
                "transport_2026_qf436_syd_mel",
                "transport_2026_vline_mel_geelong",
                "transport_2026_skybus_mel_city",
            ],
        ),
        f"{QANTAS},{QANTAS}",
        "not-an-id",
    ],
    ids=["more-than-four", "repeated", "malformed"],
)
def test_compare_rejects_an_invalid_selection(client: httpx.Client, ids: str) -> None:
    response = client.get("/transport-options/compare", params={"ids": ids})

    assert response.status_code == 422
    assert detail_fields(response) == ["ids"]
