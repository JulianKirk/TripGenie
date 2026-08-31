"""End-to-end tests for the public accommodation API, driven through
TestClient against the real database service over ASGI. Covers the contract in
student-2/docs/backend-service-api.md.

Rows are seeded through the database service's own POST -- this service has no
write path, by design.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.database.test_internal_api import CABIN, HOTEL

NO_ROUTE = "no route to the database service"
TOO_SLOW = "slower than DB_TIMEOUT"


@pytest.fixture
def hotel_id(database):
    return database.post("/internal/accommodation", json=HOTEL).json()["id"]


@pytest.fixture
def seeded(database):
    for row in (HOTEL, CABIN):
        database.post("/internal/accommodation", json=row)


def query(client, **filters):
    return client.request("QUERY", "/accommodation", json=filters)


class TestHealth:
    def test_reports_both_services_when_the_database_is_up(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "student-2-backend",
            "database": "ok",
        }

    def test_degraded_but_still_200_when_the_database_is_unreachable(self, mock_client):
        """The question this endpoint answers is whether *this* service is
        running, and it is -- so an unreachable database is a 200 that says
        so, not a 503."""

        def unreachable(request):
            raise httpx.ConnectError(NO_ROUTE, request=request)

        with mock_client(unreachable) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "degraded",
            "service": "student-2-backend",
            "database": "unreachable",
        }


class TestGetAccommodation:
    def test_returns_the_full_message(self, client, hotel_id):
        body = client.get(f"/accommodation/{hotel_id}").json()
        assert body["name"] == "example accommodation"
        assert body["price_per_night"] == 1.0
        assert body["amenities"] == ["wifi", "pool"]
        assert body["location_details"]["street_number"] == 123
        assert body["room_details"]["bed_types"] == ["king", "queen"]

    def test_the_message_survives_the_wrapper_unchanged(self, client, database):
        """This service declares the accommodation message separately from the
        database service, so the two have to agree field for field. They are
        the same request one hop apart -- any difference is drift."""
        row_id = database.post("/internal/accommodation", json=CABIN).json()["id"]
        assert (
            client.get(f"/accommodation/{row_id}").json()
            == database.get(f"/internal/accommodation/{row_id}").json()
        )

    def test_a_relation_the_row_does_not_have_is_absent(self, client, database):
        """The message is one nullable class, so a response says what it means
        by which fields are present."""
        no_rooms = {k: v for k, v in CABIN.items() if k != "room_details"}
        row_id = database.post("/internal/accommodation", json=no_rooms).json()["id"]
        assert "room_details" not in client.get(f"/accommodation/{row_id}").json()

    def test_the_databases_404_reaches_the_caller(self, client):
        response = client.get(f"/accommodation/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "accommodation not found"

    def test_a_non_uuid_id_is_404_not_a_validation_error(self, client):
        assert client.get("/accommodation/garbage").status_code == 404


class TestListAccommodation:
    def test_lists_everything_by_default(self, client, seeded):
        body = client.get("/accommodation").json()
        assert body["total"] == 2
        assert len(body["accommodations"]) == 2

    def test_rows_are_trimmed(self, client, seeded):
        """A list is for choosing which accommodation to GET in full."""
        row = client.get("/accommodation").json()["accommodations"][0]
        assert set(row["location_details"]) == {"country", "city"}
        assert "amenities" not in row
        assert "room_details" not in row

    def test_limit_pages_but_total_counts_every_match(self, client, seeded):
        body = client.get("/accommodation?limit=1").json()
        assert len(body["accommodations"]) == 1
        assert body["total"] == 2

    def test_offset_skips(self, client, seeded):
        first = client.get("/accommodation?limit=1").json()["accommodations"][0]
        second = client.get("/accommodation?limit=1&offset=1").json()["accommodations"][
            0
        ]
        assert first["id"] != second["id"]

    @pytest.mark.parametrize("params", ["limit=0", "limit=101", "offset=-1"])
    def test_out_of_range_paging_is_400_not_422(self, client, params):
        assert client.get(f"/accommodation?{params}").status_code == 400


class TestQueryAccommodation:
    def test_no_filters_returns_everything(self, client, seeded):
        assert query(client).json()["total"] == 2

    def test_filters_stack(self, client, seeded):
        body = query(
            client,
            accommodation={
                "type": "hotel",
                "location_details": {"country": "australia", "city": "sydney"},
            },
            price_max=250,
            room_count_min=2,
        ).json()
        assert [a["name"] for a in body["accommodations"]] == ["example accommodation"]
        assert body["total"] == 1

    def test_city_without_country_is_400(self, client, seeded):
        response = query(client, accommodation={"location_details": {"city": "sydney"}})
        assert response.status_code == 400

    def test_an_unknown_filter_is_400_not_silently_ignored(self, client, seeded):
        assert query(client, room_count_minimum=2).status_code == 400
        assert query(client, accommodation={"contry": "australia"}).status_code == 400

    def test_an_unset_bound_is_not_forwarded_as_null(self, client, seeded):
        """The database service forbids unknown fields but would accept an
        explicit null bound and filter on it, so an all-defaults QUERY must
        still match everything."""
        assert query(client, limit=20).json()["total"] == 2


class TestDatabaseFailures:
    """The statuses that originate here: the request was fine, the data was
    not reachable."""

    def test_a_timeout_is_503(self, mock_client):
        def slow(request):
            raise httpx.ReadTimeout(TOO_SLOW, request=request)

        with mock_client(slow) as client:
            response = client.get("/accommodation")
        assert response.status_code == 503
        assert response.json()["detail"] == "database service unavailable"

    def test_a_database_500_is_502(self, mock_client):
        with mock_client(lambda _: httpx.Response(500, json={"detail": "boom"})) as c:
            response = c.get("/accommodation")
        assert response.status_code == 502
        assert response.json()["detail"] == "bad response from database service"

    def test_a_non_json_body_is_502(self, mock_client):
        with mock_client(lambda _: httpx.Response(200, text="<html>nope")) as client:
            response = client.get("/accommodation")
        assert response.status_code == 502

    def test_an_unexpected_shape_is_502(self, mock_client):
        """This service declares the accommodation message itself, so a
        database service that drifts fails loudly here rather than passing
        something unusable through."""
        with mock_client(lambda _: httpx.Response(200, json={"rows": []})) as client:
            response = client.get("/accommodation")
        assert response.status_code == 502
