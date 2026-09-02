"""Tests for the accommodation frontend service.

Two things can break here: the form-to-QUERY-body translation, and the HTML.
Both are asserted on directly -- the body as the dict the backend received, the
HTML as substrings, which is the same approach student 1's frontend tests take.
"""

from __future__ import annotations

import re

import httpx

from tests.frontend.conftest import LISTING

HTMX = {"HX-Request": "true"}


class TestPage:
    def test_index_is_a_whole_page_with_the_filter_form(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.text
        assert 'id="filters"' in response.text
        assert LISTING["name"] in response.text

    def test_results_are_a_fragment(self, client):
        response = client.get("/accommodation", headers=HTMX)
        assert response.status_code == 200
        assert "<!DOCTYPE html>" not in response.text
        assert LISTING["name"] in response.text

    def test_health_reports_the_backend(self, client):
        body = client.get("/health").json()
        assert body == {
            "status": "ok",
            "service": "student-2-frontend",
            "backend": "ok",
        }


class TestQueryBody:
    def test_an_empty_form_filters_on_nothing(self, client, backend):
        client.get("/accommodation")
        assert backend.body == {"accommodation": {}, "limit": 20, "offset": 0}

    def test_a_blank_input_is_not_a_filter(self, client, backend):
        client.get("/accommodation?name=&type=")
        assert backend.body["accommodation"] == {}

    def test_search_text_goes_in_as_the_name(self, client, backend):
        client.get("/accommodation?name=hil")
        assert backend.body["accommodation"] == {"name": "hil"}

    def test_nested_fields_are_nested(self, client, backend):
        client.get("/accommodation?country=australia&city=sydney&room_count=2")
        assert backend.body["accommodation"] == {
            "location_details": {"country": "australia", "city": "sydney"},
            "room_details": {"room_count": "2"},
        }

    def test_a_city_without_a_country_is_dropped(self, client, backend):
        """The backend 400s on it, so the page never sends one."""
        client.get("/accommodation?city=sydney")
        assert backend.body["accommodation"] == {}

    def test_amenities_arrive_as_a_list(self, client, backend):
        client.get("/accommodation?amenities=wifi&amenities=pool")
        assert backend.body["accommodation"] == {"amenities": ["wifi", "pool"]}

    def test_bounds_are_forwarded(self, client, backend):
        client.get("/accommodation?price_max=250&rating_min=4&bed_count_min=2")
        assert backend.body["price_max"] == "250"
        assert backend.body["rating_min"] == "4"
        assert backend.body["bed_count_min"] == "2"

    def test_paging_is_forwarded(self, client, backend):
        client.get("/accommodation?limit=50&offset=100")
        assert backend.body["limit"] == 50
        assert backend.body["offset"] == 100

    def test_junk_paging_falls_back_instead_of_400ing(self, client, backend):
        client.get("/accommodation?limit=abc&offset=-5")
        assert backend.body["limit"] == 20
        assert backend.body["offset"] == 0

    def test_an_oversized_page_is_clamped_to_what_the_backend_allows(
        self, client, backend
    ):
        client.get("/accommodation?limit=5000")
        assert backend.body["limit"] == 100


class TestPager:
    def test_no_pager_when_everything_fits(self, client, backend):
        response = client.get("/accommodation")
        assert "Showing 1\u20131 of 1" in response.text
        assert "Previous" not in response.text

    def test_pager_counts_the_whole_match(self, client, backend):
        backend.response = httpx.Response(
            200, json={"accommodations": [LISTING] * 20, "total": 45}
        )
        response = client.get("/accommodation?offset=20")
        assert "Showing 21\u201340 of 45" in response.text
        assert "Page 2 of 3" in response.text

    def test_no_matches_says_so(self, client, backend):
        backend.response = httpx.Response(200, json={"accommodations": [], "total": 0})
        response = client.get("/accommodation")
        assert "No accommodations match these filters." in response.text


class TestDetail:
    def test_modal_carries_the_fields_the_list_leaves_out(self, client):
        response = client.get(
            "/accommodation/3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11", headers=HTMX
        )
        assert "<dialog" in response.text
        assert "Rooms over Circular Quay." in response.text
        assert "Wifi, Pool" in response.text
        assert "King" in response.text

    def test_a_bad_id_is_a_404_from_routing_not_a_backend_call(self, client):
        assert client.get("/accommodation/not-a-uuid").status_code == 404


class TestErrors:
    def test_an_unreachable_backend_becomes_a_message_not_a_500(self, client, backend):
        def explode(request):
            message = "no route to host"
            raise httpx.ConnectError(message, request=request)

        client.app.state.backend = httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(explode)
        )
        response = client.get("/accommodation")
        assert response.status_code == 200
        assert "not responding" in response.text

    def test_a_backend_400_shows_what_it_said(self, client, backend):
        backend.response = httpx.Response(400, json={"detail": "city requires country"})
        response = client.get("/accommodation")
        assert "city requires country" in response.text

    def test_the_page_still_renders_when_the_backend_is_down(self, client, backend):
        backend.response = httpx.Response(503, json={"detail": "database unavailable"})
        response = client.get("/")
        assert "<!DOCTYPE html>" in response.text
        assert "database unavailable" in response.text


class TestListingPayloadRendersFaithfully:
    """Body assertions for the listing and filter endpoints.

    The tests above cover the request this service *sends* and that the name
    comes back. These cover the other half: that every field of the payload
    reaches the page as the value the backend gave, formatted but not altered.
    A row that 200s with the wrong price is worse than one that fails.
    """

    def _row(self, text: str) -> str:
        start = text.index('<tr class="results__row"')
        return text[start : text.index("</tr>", start)]

    def _cells(self, text: str) -> list[str]:
        """The row's data cells, tags stripped and whitespace collapsed.

        Per-cell rather than a substring search over the whole row: "Hotel"
        appears in "Harbour View Hotel", so asserting it against the row would
        pass whether or not the type column rendered at all.
        """
        row = self._row(text)
        return [
            " ".join(re.sub(r"<[^>]+>", " ", cell).split())
            for cell in re.findall(r"<td>(.*?)</td>", row, re.DOTALL)
        ]

    def test_every_column_of_a_row_carries_its_value(self, client):
        cells = self._cells(client.get("/accommodation").text)

        # type, location, price, rating, availability -- in that order.
        assert cells == [
            "Hotel",
            "Sydney, Australia",
            "$320.00",
            "4.6 / 5",
            "Available",
        ]
        assert "pill--available" in self._row(client.get("/accommodation").text)
        assert LISTING["name"] in self._row(client.get("/accommodation").text)

    def test_a_null_price_and_rating_render_as_absences_not_zeroes(
        self, client, backend
    ):
        """A missing price is not a free room."""
        backend.response = httpx.Response(
            200,
            json={
                "accommodations": [
                    {**LISTING, "price_per_night": None, "rating": None}
                ],
                "total": 1,
            },
        )

        cells = self._cells(client.get("/accommodation").text)

        assert cells[2] == "\u2014"  # an em dash, not $0.00
        assert cells[3] == "Unrated"

    def test_a_filtered_response_renders_what_came_back_not_what_was_asked(
        self, client, backend
    ):
        """The page must draw the backend's answer. Echoing the filter instead
        would look identical whenever the two happen to agree."""
        backend.response = httpx.Response(
            200,
            json={
                "accommodations": [
                    {**LISTING, "name": "Blue Mountains Lodge", "price_per_night": 95.5}
                ],
                "total": 1,
            },
        )

        text = client.get("/accommodation?name=harbour").text

        assert "Blue Mountains Lodge" in text
        assert "$95.50" in text
        assert "Harbour View Hotel" not in text

    def test_the_row_links_to_that_accommodations_own_detail(self, client):
        row = self._row(client.get("/accommodation").text)

        assert f"/accommodation/{LISTING['id']}" in row

    def test_the_whole_page_and_a_deep_link_both_carry_the_listing(self, client):
        """The deep link renders a modal *and* the list behind it -- opening
        one accommodation must not cost the page it opened from."""
        listing_only = client.get("/").text
        with_modal = client.get(f"/?accommodation={LISTING['id']}").text

        for text in (listing_only, with_modal):
            assert LISTING["name"] in text
            assert "$320.00" in text
        assert "<dialog" in with_modal
