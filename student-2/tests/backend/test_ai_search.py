"""The ask box: a question in English becomes a search this service can run.

No model anywhere here. AI-Mode is a `httpx.MockTransport` that returns whatever
string a test says "the model said", which is the only interesting variable --
everything downstream of that string is ordinary search, already covered by
tests/e2e.

What is worth asserting is the boundary: the schema we hand the model is the
filter contract itself, the caller's paging survives whatever the model claims,
a bad answer is retried and then given up on, and none of this can take the rest
of the service down with it.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from uuid import UUID, uuid5

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_service.ai_search import UNUSABLE
from backend_service.app import create_app
from backend_service.config import Settings
from backend_service.schemas import AiSearchAnswer

DATABASE_URL = "http://database.test"
LOCATION_URL = "http://location.test"
AI_MODE_URL = "http://ai-mode.test"
NO_ROUTE = "no route to ai-mode"

# The shared service's id rule, copied from shared/docs/object-model.md the same
# way seed_data.py copies it -- there is no shared service running here.
LOCATION_NAMESPACE = UUID("9a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b")
JAPAN = uuid5(LOCATION_NAMESPACE, "country:japan")

QUESTION = "what are some good accommodation around japan under 100 a night"
REPLY = "Looking for well-rated places in Japan under 100 a night."
UNDER_100_IN_JAPAN = {
    "accommodation": {"location_details": {"country": "japan"}},
    "price_max": 100,
    "rating_min": 4,
    "reply": REPLY,
}


TOKYO = uuid5(LOCATION_NAMESPACE, "city:japan:tokyo")
SYDNEY_AU = uuid5(LOCATION_NAMESPACE, "city:australia:sydney")
AUSTRALIA = uuid5(LOCATION_NAMESPACE, "country:australia")
CANADA = uuid5(LOCATION_NAMESPACE, "country:canada")
SYDNEY_CA = uuid5(LOCATION_NAMESPACE, "city:canada:sydney")


def places(request):
    """A shared reference service with three countries, and a city name that
    two of them share -- Sydney is in Australia and in Nova Scotia."""
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if "country" in str(request.url):
        body = {
            "countries": [
                {"id": str(JAPAN), "name": "japan"},
                {"id": str(AUSTRALIA), "name": "australia"},
                {"id": str(CANADA), "name": "canada"},
            ],
            "total": 3,
        }
    else:
        body = {
            "cities": [
                {"id": str(TOKYO), "country_id": str(JAPAN), "name": "tokyo"},
                {
                    "id": str(SYDNEY_AU),
                    "country_id": str(AUSTRALIA),
                    "name": "sydney",
                },
                {"id": str(SYDNEY_CA), "country_id": str(CANADA), "name": "sydney"},
            ],
            "total": 3,
        }
    return httpx.Response(200, json=body)


class FakeAiMode:
    """The shared AI-Mode service, as far as this service can tell.

    Answers are queued as strings -- what the model produced -- and wrapped in
    the `{"data": ...}` envelope the real service uses. A queued exception is
    raised instead, which is how an unreachable service is tested.
    """

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.schemas: list[dict] = []

    def handle(self, request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"data": {"status": "ok"}})
        body = json.loads(request.content)
        self.prompts.append(body["prompt"])
        self.schemas.append(body["schema"])
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(
            200,
            json={
                "data": {
                    "run_id": "aimode_000000000001",
                    "correlation_id": "aimode_000000000001",
                    "model": "qwen2.5:0.5b",
                    "provider": "ollama",
                    "response": answer,
                    "done": True,
                }
            },
        )


class FakeDatabase:
    """The database service, recording the search it was asked to run."""

    def __init__(self):
        self.bodies: list[dict] = []

    def handle(self, request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"accommodations": [], "total": 0})


@pytest.fixture
def ai_client():
    """A backend wired to a fake AI-Mode, a fake database and a shared service
    that has heard of japan."""

    @contextmanager
    def factory(ai, **overrides):
        database = FakeDatabase()
        app = create_app(
            Settings(
                database_url=DATABASE_URL,
                location_url=LOCATION_URL,
                ai_mode_url=AI_MODE_URL,
                **overrides,
            ),
            transport=httpx.MockTransport(database.handle),
            location_transport=httpx.MockTransport(places),
            ai_transport=httpx.MockTransport(ai.handle),
        )
        with TestClient(app) as client:
            yield client, database

    return factory


class TestAskingAQuestion:
    def test_the_model_s_filters_become_the_search_that_runs(self, ai_client):
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, database):
            response = client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert response.status_code == 200
        # The country name left as the id the database service stores, the same
        # swap an ordinary QUERY does. One search path, not two.
        assert database.bodies == [
            {
                "accommodation": {"location_details": {"country_id": str(JAPAN)}},
                "price_max": 100.0,
                "rating_min": 4.0,
                "limit": 20,
                "offset": 0,
            }
        ]

    def test_the_reply_says_what_the_question_was_understood_to_mean(self, ai_client):
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, _):
            body = client.post(
                "/accommodation/ai-search", json={"query": QUESTION}
            ).json()

        # Publishable as-is to QUERY /accommodation: the page can re-run or edit
        # the search without going near the model again.
        assert body["query_used"]["accommodation"]["location_details"] == {
            "country": "japan"
        }
        assert body["query_used"]["price_max"] == 100
        # The model's sentence rides along; it is not a filter, so it stays out
        # of the re-runnable search.
        assert body["reply"] == REPLY
        assert "reply" not in body["query_used"]
        assert body["accommodations"] == []
        assert body["total"] == 0

    def test_the_model_must_decide_on_every_filter_it_is_offered(self, ai_client):
        """Optional everywhere, the shortest completion the grammar allows is
        `{"reply": "..."}` -- a sentence and no search at all, which is what
        llama3.1:8b answered "cheap things around adelaide" with. Required at
        the top level, it has to say something about each one.

        Not required inside the template: with no way to skip, the model fills
        it with invention -- a price of 0, a type nobody asked for -- and each
        of those is an exact match that empties the result."""
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, _):
            client.post("/accommodation/ai-search", json={"query": QUESTION})

        sent = ai.schemas[0]
        assert set(sent["required"]) == set(sent["properties"])
        assert "required" not in sent["$defs"]["Accommodation"]
        assert "required" not in sent["$defs"]["Location"]

    def test_a_bound_that_bounds_everything_comes_off_too(self, ai_client):
        """The other half of the same behaviour, and the dangerous half: asked
        about "budget places in sydney", llama3.1:8b answered `price_max: 0` --
        a search no accommodation can match. An empty result for a question with
        a real answer is worse than an unfiltered one."""
        ai = FakeAiMode(
            json.dumps(
                {
                    "accommodation": {"location_details": {"country": "japan"}},
                    "price_max": 0,
                    "rating_max": 0,
                    "reply": "Looking for budget places in Japan.",
                }
            )
        )
        with ai_client(ai) as (client, database):
            body = client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert body.json()["query_used"].keys() == {"accommodation", "limit", "offset"}
        assert "price_max" not in database.bodies[0]

    def test_a_bound_that_bounds_nothing_comes_off(self, ai_client):
        """Made to answer with a bound it was not given, the model says "no
        bound" in numbers. They are noise in the search and, because the page
        prints the filters back to the reader, noise on the page."""
        ai = FakeAiMode(
            json.dumps(
                {
                    "accommodation": {"location_details": {"country": "japan"}},
                    "price_min": 0,
                    "price_max": 1000000000,
                    "rating_min": 0,
                    "rating_max": 5,
                    "room_count_min": 1,
                    "bed_count_min": 4,
                    "reply": "Looking for places in Japan that sleep four.",
                }
            )
        )
        with ai_client(ai) as (client, database):
            body = client.post("/accommodation/ai-search", json={"query": QUESTION})

        used = body.json()["query_used"]
        assert used.keys() == {"accommodation", "bed_count_min", "limit", "offset"}
        # The one real bound survives.
        assert used["bed_count_min"] == 4
        assert database.bodies[0]["bed_count_min"] == 4

    def test_the_schema_sent_is_the_filter_contract_minus_the_unaskable(
        self, ai_client
    ):
        """Derived from the contract, not written out beside it, so a new filter
        reaches the model the moment schemas.py has one."""
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, _):
            client.post("/accommodation/ai-search", json={"query": QUESTION})

        sent = ai.schemas[0]
        contract = AiSearchAnswer.model_json_schema()
        assert sent["properties"].keys() == contract["properties"].keys() - {
            "limit",
            "offset",
        }
        # A sentence cannot say a street number, and constrained decoding will
        # invent one if the schema offers the field. A place name it can say --
        # constrained to the real ones, see below.
        assert sent["$defs"]["Location"]["properties"].keys() == {"country", "city"}
        assert "room_details" not in sent["$defs"]["Accommodation"]["properties"]
        # Everything a question can actually imply is still on offer.
        assert "price_max" in sent["properties"]
        assert "rating_min" in sent["properties"]
        assert "room_count_min" in sent["properties"]
        assert "amenities" in sent["$defs"]["Accommodation"]["properties"]
        # The sentence for the reader is decoded in the same pass as the
        # filters, not asked for in a second call.
        assert "reply" in sent["properties"]

    def test_the_places_offered_are_the_ones_that_exist(self, ai_client):
        """Both place fields are enums of the shared service's own names, not
        free text. Given a free-text field, qwen2.5:0.5b answers "kyoto" for
        Japan and "canberra" for Australia -- confident, plausible, and an exact
        match on a place with no listings. Decoding cannot produce a name that
        is not on the list."""
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, _):
            client.post("/accommodation/ai-search", json={"query": QUESTION})

        location = ai.schemas[0]["$defs"]["Location"]["properties"]
        assert location["country"]["enum"] == ["australia", "canada", "japan"]
        assert location["city"]["enum"] == ["sydney", "tokyo"]

    def test_a_city_with_no_country_gets_the_country_it_is_in(self, ai_client):
        """ "cheap things around adelaide" names a city and no country, and
        `city requires country` would reject it. The country is not the
        traveller's to supply: this service holds the list that maps one to the
        other, so it fills it in rather than spending a retry."""
        ai = FakeAiMode(
            json.dumps(
                {
                    "accommodation": {"location_details": {"city": "tokyo"}},
                    "reply": "Looking for places around Tokyo.",
                }
            )
        )
        with ai_client(ai) as (client, database):
            body = client.post(
                "/accommodation/ai-search", json={"query": "cheap things in tokyo"}
            ).json()

        assert len(ai.prompts) == 1  # no retry was needed
        assert body["query_used"]["accommodation"]["location_details"] == {
            "country": "japan",
            "city": "tokyo",
        }
        assert database.bodies[0]["accommodation"]["location_details"] == {
            "country_id": str(JAPAN),
            "city_id": str(TOKYO),
        }

    def test_a_city_two_countries_share_is_dropped_rather_than_guessed(self, ai_client):
        """Sydney is in Australia and in Canada. Picking one for a traveller who
        did not say is worse than not filtering on the place at all."""
        ai = FakeAiMode(
            json.dumps(
                {
                    "accommodation": {"location_details": {"city": "sydney"}},
                    "reply": "Looking for places around Sydney.",
                }
            )
        )
        with ai_client(ai) as (client, database):
            body = client.post(
                "/accommodation/ai-search", json={"query": "somewhere in sydney"}
            ).json()

        # An empty place template filters on nothing, so the search is the
        # whole list rather than half of Sydney.
        assert body["query_used"]["accommodation"]["location_details"] == {}
        assert database.bodies[0]["accommodation"] == {"location_details": {}}

    def test_the_prompt_names_the_countries_that_have_listings(self, ai_client):
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, _):
            client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert "japan" in ai.prompts[0]
        assert "tokyo" in ai.prompts[0]
        assert QUESTION in ai.prompts[0]

    def test_the_prompt_ends_on_a_cue_the_model_completes(self, ai_client):
        """AI-Mode strips trailing whitespace off a prompt, and sends it to
        Ollama with no chat template. A prompt that ends on a blank line gets
        `{ }` back -- schema-valid, and a search for nothing. See
        `ai_search.render_prompt`."""
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, _):
            client.post("/accommodation/ai-search", json={"query": QUESTION})

        prompt = ai.prompts[0]
        assert prompt == prompt.strip()
        assert prompt.endswith(":")

    def test_the_caller_s_paging_wins_over_the_model_s(self, ai_client):
        ai = FakeAiMode(json.dumps(UNDER_100_IN_JAPAN | {"limit": 100, "offset": 40}))
        with ai_client(ai) as (client, database):
            client.post(
                "/accommodation/ai-search",
                json={"query": QUESTION, "limit": 10, "offset": 20},
            )

        assert database.bodies[0]["limit"] == 10
        assert database.bodies[0]["offset"] == 20

    def test_a_country_nobody_has_heard_of_is_an_empty_result(self, ai_client):
        ai = FakeAiMode(
            json.dumps(
                {
                    "accommodation": {"location_details": {"country": "narnia"}},
                    "reply": "Looking for places in Narnia.",
                }
            )
        )
        with ai_client(ai) as (client, database):
            response = client.post(
                "/accommodation/ai-search", json={"query": "somewhere in narnia"}
            )

        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert database.bodies == []


class TestAnAnswerThisServiceCannotUse:
    def test_a_reply_that_is_not_json_is_retried(self, ai_client):
        ai = FakeAiMode("here you go!", json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai) as (client, database):
            response = client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert response.status_code == 200
        assert len(database.bodies) == 1
        # The second prompt tells the model what was wrong with the first.
        assert "could not be used" in ai.prompts[1]

    def test_a_reply_that_misses_the_schema_is_retried(self, ai_client):
        ai = FakeAiMode(
            json.dumps({"price_max": "cheap", "reply": REPLY}),
            json.dumps(UNDER_100_IN_JAPAN),
        )
        with ai_client(ai) as (client, _):
            response = client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert response.status_code == 200
        assert "price_max" in ai.prompts[1]

    def test_retries_exhausted_is_a_502(self, ai_client):
        ai = FakeAiMode("nope", "still nope")
        with ai_client(ai) as (client, database):
            response = client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert response.status_code == 502
        assert response.json()["detail"] == UNUSABLE
        assert database.bodies == []

    def test_attempts_are_configurable(self, ai_client):
        ai = FakeAiMode("no", "no", json.dumps(UNDER_100_IN_JAPAN))
        with ai_client(ai, ai_max_attempts=3) as (client, _):
            assert (
                client.post(
                    "/accommodation/ai-search", json={"query": QUESTION}
                ).status_code
                == 200
            )

    def test_a_question_is_never_written_to_the_log(self, ai_client, caplog):
        ai = FakeAiMode("nope", "still nope")
        with caplog.at_level("INFO"), ai_client(ai) as (client, _):
            client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert "japan" not in caplog.text
        assert "rejected" in caplog.text


class TestWhenAiModeIsNotThere:
    def test_an_unreachable_service_is_the_documented_503(self, ai_client):
        ai = FakeAiMode(httpx.ConnectError(NO_ROUTE))
        with ai_client(ai) as (client, _):
            response = client.post("/accommodation/ai-search", json={"query": QUESTION})

        assert response.status_code == 503
        assert response.json()["detail"] == "ai mode service unavailable"

    def test_ordinary_search_still_works(self, ai_client):
        """The ask box is an extra. Losing it must not cost the page its
        results, its pager or its modal."""
        ai = FakeAiMode(httpx.ConnectError(NO_ROUTE))
        with ai_client(ai) as (client, _):
            assert client.get("/accommodation").status_code == 200
            assert (
                client.post(
                    "/accommodation/ai-search", json={"query": QUESTION}
                ).status_code
                == 503
            )

    def test_a_configured_service_that_is_down_is_degraded(self, ai_client):
        class Down(FakeAiMode):
            def handle(self, request):
                raise httpx.ConnectError(NO_ROUTE)

        with ai_client(Down()) as (client, _):
            health = client.get("/health").json()

        assert health["ai_mode"] == "unreachable"
        # Configured and unreachable is a fault, unlike never configured.
        assert health["status"] == "degraded"

    def test_an_unconfigured_service_is_healthy_and_the_route_says_so(self):
        """No AI_MODE_URL at all: the accommodation service is a search service
        that happens to have an ask box, so it boots and serves without one."""
        database = FakeDatabase()
        app = create_app(
            Settings(database_url=DATABASE_URL, location_url=LOCATION_URL),
            transport=httpx.MockTransport(database.handle),
            location_transport=httpx.MockTransport(places),
        )
        with TestClient(app) as client:
            health = client.get("/health").json()
            assert health["ai_mode"] == "not_configured"
            assert health["status"] == "ok"

            response = client.post("/accommodation/ai-search", json={"query": QUESTION})
            assert response.status_code == 503
            assert response.json()["detail"] == "ai mode is not configured"
