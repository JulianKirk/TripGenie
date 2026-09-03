"""The ask box, and what it does to the page.

The interesting part is not the rows -- those are the same fragment every other
search renders. It is that the filter form comes back filled in with what the
question was understood to mean, so the page ends up in a state the user could
have typed, and everything downstream of the form keeps working.
"""

from __future__ import annotations

import httpx

from tests.frontend.conftest import AI_QUERY_USED, AI_REPLY

HTMX = {"HX-Request": "true"}
QUESTION = "what are some good accommodation around japan under 100 a night"


class TestTheAskBox:
    def test_the_page_offers_one(self, client):
        page = client.get("/").text
        assert 'name="query"' in page
        assert "/accommodation/ai-search" in page

    def test_the_question_reaches_the_backend(self, client, backend):
        client.post(
            "/accommodation/ai-search", data={"query": f"  {QUESTION}  "}, headers=HTMX
        )
        assert backend.ai_question == QUESTION

    def test_the_rows_are_rendered_like_any_other_search(self, client):
        html = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        ).text
        assert "Harbour View Hotel" in html
        assert "of 1" in html

    def test_it_says_how_the_question_was_read(self, client):
        html = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        ).text
        assert "country japan" in html
        assert "price max 100" in html

    def test_the_ask_waits_longer_than_an_ordinary_search(self, client, backend):
        """A local model answers in tens of seconds. The page's ordinary 5s
        would give up while the backend is still working and tell the reader the
        service is down, which it is not."""
        client.post("/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX)
        assert backend.ai_timeout > 60

    def test_the_model_s_own_sentence_is_on_the_page(self, client):
        """The filters say the same thing in field names; this is the answer a
        person reads."""
        html = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        ).text
        assert AI_REPLY in html

    def test_the_answer_lands_under_the_ask_box_not_in_the_results(self, client):
        """It is the answer to the question, so it belongs next to the question.
        Out of band, because the response itself swaps #results."""
        html = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        ).text
        answer = html[html.index('id="ai-answer"') :]
        assert 'hx-swap-oob="true"' in answer[: answer.index(">")]
        assert AI_REPLY in answer[: answer.index("</div>")]

    def test_an_ordinary_search_clears_a_stale_answer(self, client):
        """A question that has been answered stays on the page until the page is
        searched by hand -- and then it is no longer what the results are."""
        html = client.get("/accommodation", headers=HTMX).text
        answer = html[html.index('id="ai-answer"') :]
        assert 'hx-swap-oob="true"' in answer[: answer.index(">")]
        assert answer[: answer.index("</div>")].count("<p") == 0

    def test_the_page_says_the_wait_is_a_wait(self, client):
        """A local model takes tens of seconds. Without something moving, that
        is indistinguishable from a hang."""
        page = client.get("/").text
        assert 'hx-indicator="#asking"' in page
        assert 'id="asking" class="htmx-indicator asking"' in page
        assert "asking__bar" in page

    def test_the_filter_form_comes_back_filled_in_out_of_band(self, client):
        html = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        ).text
        # Out of band, so one response updates both #results and the form that
        # every pager link and filter change reads from.
        assert 'hx-swap-oob="true"' in html
        assert 'name="country" type="search" autocomplete="off" value="japan"' in html
        assert 'name="price_max" type="number" min="0" step="1" value="100.0"' in html

    def test_an_empty_ask_is_the_unfiltered_list(self, client, backend):
        html = client.post(
            "/accommodation/ai-search", data={"query": "   "}, headers=HTMX
        ).text
        assert backend.ai_question is None
        assert "Harbour View Hotel" in html

    def test_a_failure_renders_where_the_results_would_have_been(self, client, backend):
        backend.ai_response = httpx.Response(
            502, json={"detail": "ai mode returned an unusable search"}
        )
        response = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        )
        assert response.status_code == 200
        assert "ai mode returned an unusable search" in response.text

    def test_an_unreachable_backend_does_not_break_the_page(self, client, backend):
        backend.ai_response = httpx.Response(503, json={})
        html = client.post(
            "/accommodation/ai-search", data={"query": QUESTION}, headers=HTMX
        ).text
        assert "not responding" in html


class TestFormValues:
    def test_a_search_becomes_the_form_that_would_have_produced_it(self):
        from frontend_service.app import form_values, query_body

        params = form_values(AI_QUERY_USED)
        assert params["country"] == "japan"
        assert params["price_max"] == "100.0"

        # The round trip is what matters: the form the ask box fills in has to
        # produce the same search when the user changes something else in it.
        assert query_body(params)["accommodation"] == AI_QUERY_USED["accommodation"]

    def test_every_filter_survives_the_round_trip(self):
        from starlette.datastructures import QueryParams

        from frontend_service.app import form_values, query_body

        typed = QueryParams(
            [
                ("name", "hostel"),
                ("description", "quiet"),
                ("type", "hostel"),
                ("availability_status", "available"),
                ("country", "japan"),
                ("city", "tokyo"),
                ("street", "kabukicho"),
                ("street_number", "3"),
                ("room_count", "2"),
                ("bed_count", "4"),
                ("room_description", "bunks"),
                ("price_min", "20"),
                ("price_max", "100"),
                ("rating_min", "4"),
                ("rating_max", "5"),
                ("room_count_min", "1"),
                ("bed_count_min", "2"),
                ("amenities", "wifi"),
                ("amenities", "laundry"),
            ]
        )
        body = query_body(typed)
        assert query_body(form_values(body)) == body
