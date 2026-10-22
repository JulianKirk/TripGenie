"""Features a deployment has switched off, as the page shows them.

The cloud profile has no AI-Mode, RAG server or Multi-Agent Server, and the
backend says so on `/health`. The page must tell the user those features are
unavailable instead of offering boxes that can only fail.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from frontend_service.app import create_app
from frontend_service.config import Settings
from tests.frontend.conftest import FakeBackend

CLOUD = {
    "status": "ok",
    "ai_mode": "not_configured",
    "rag": "not_configured",
    "multi_agent": "disabled",
}
LOCAL = {"status": "ok", "ai_mode": "ok", "rag": "configured", "multi_agent": "enabled"}


@pytest.fixture
def deployed():
    """The HTML of `path`, served by a page whose backend reports `/health`."""

    def factory(health: dict | httpx.Response, path: str = "/") -> str:
        backend = FakeBackend()

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                if isinstance(health, httpx.Response):
                    return health
                return httpx.Response(200, json=health)
            return backend.handle(request)

        app = create_app(
            Settings(backend_url="http://backend.test"),
            transport=httpx.MockTransport(handle),
        )
        with TestClient(app) as client:
            return client.get(path).text

    return factory


class TestCloud:
    def test_the_ask_box_says_ai_is_off_and_cannot_be_used(self, deployed):
        html = deployed(CLOUD)
        assert "AI features are switched off in this deployment" in html
        assert "unavailable in this deployment" in html
        assert html.count('type="radio"') == 3
        assert html.count("disabled") >= 5  # three radios, the input, the button
        assert (
            "checked" not in html.split('class="ask__modes"')[1].split("</fieldset>")[0]
        )

    def test_the_filters_and_listings_still_work(self, deployed):
        html = deployed(CLOUD)
        assert "Harbour View Hotel" in html
        assert 'id="results"' in html

    def test_the_agents_link_is_greyed_out_and_goes_nowhere(self, deployed):
        html = deployed(CLOUD)
        assert "Plan with agents (unavailable)" in html
        assert 'href="/agents"' not in html

    def test_the_agents_page_explains_and_disables_the_form(self, deployed):
        html = deployed(CLOUD, "/agents")
        assert "Multi-agent planning is switched off in this deployment" in html
        assert '<fieldset class="agents__fieldset" disabled>' in html


class TestLocal:
    def test_everything_is_on(self, deployed):
        html = deployed(LOCAL)
        assert "switched off" not in html
        assert "unavailable in this deployment" not in html
        assert 'href="/agents"' in html
        assert 'value="search" checked' in html

    def test_the_agents_form_is_usable(self, deployed):
        html = deployed(LOCAL, "/agents")
        assert "switched off" not in html
        assert '<fieldset class="agents__fieldset" >' in html


class TestPartial:
    def test_only_the_rag_guide_is_off(self, deployed):
        html = deployed({**LOCAL, "rag": "not_configured"})
        box = html.split('class="ask__modes"')[1].split("</fieldset>")[0]
        assert "AI features are switched off" not in html
        assert box.count("unavailable in this deployment") == 1
        assert 'value="rag" disabled' in box
        assert 'value="search" checked' in box

    def test_ai_mode_off_but_rag_on_defaults_to_the_guide(self, deployed):
        html = deployed({**LOCAL, "ai_mode": "not_configured"})
        box = html.split('class="ask__modes"')[1].split("</fieldset>")[0]
        assert 'value="search" disabled' in box
        assert 'value="mcp" disabled' in box
        assert 'value="rag" checked' in box
        assert 'id="ask-query"' in html
        assert "AI features are switched off" not in html


class TestTheBackendCannotBeAsked:
    def test_nothing_is_hidden_on_a_guess(self, deployed):
        html = deployed(httpx.Response(503, json={"detail": "down"}))
        assert "switched off" not in html
        assert 'href="/agents"' in html

    def test_an_older_backend_that_reports_nothing_counts_as_on(self, deployed):
        html = deployed({"status": "ok"})
        assert "switched off" not in html
        assert 'href="/agents"' in html
