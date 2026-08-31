"""Frontend tests -- the pages, and the form-to-JSON translation behind them.
Covers shared/user/docs/frontend-service.md.
"""

from __future__ import annotations

import httpx

from tests.frontend.conftest import MARK_ID

CREDENTIALS = {"username": "mark", "password": "hunter2"}
REFUSED = "connection refused"


class TestHealth:
    def test_health_is_ok_when_the_backend_answers(self, client):
        body = client.get("/health").json()
        assert body == {
            "status": "ok",
            "service": "shared-user-frontend",
            "backend": "ok",
        }

    def test_health_is_degraded_and_still_200_when_the_backend_is_down(
        self, client, backend
    ):
        backend.response = httpx.Response(500, json={})
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["backend"] == "unreachable"


class TestLoginPage:
    def test_the_page_offers_both_forms(self, client):
        body = client.get("/").text
        assert 'action="/login"' in body
        assert 'action="/signup"' in body

    def test_the_page_needs_nothing_from_the_backend(self, client, backend):
        client.get("/")
        assert backend.requests == []


class TestLogin:
    def test_a_good_login_redirects_to_the_account_page(self, client):
        response = client.post("/login", data=CREDENTIALS)
        assert response.status_code == 303
        assert response.headers["location"] == f"/account/{MARK_ID}"

    def test_the_form_is_sent_as_the_documented_json_body(self, client, backend):
        client.post("/login", data=CREDENTIALS)
        assert backend.requests == [("POST", "/users/login")]
        assert backend.body == CREDENTIALS

    def test_a_bad_login_re_renders_the_page_with_the_error(self, client, backend):
        backend.response = httpx.Response(
            401, json={"detail": "invalid username or password"}
        )
        response = client.post("/login", data=CREDENTIALS)
        assert response.status_code == 200
        assert "invalid username or password" in response.text

    def test_a_bad_login_keeps_the_username_but_not_the_password(self, client, backend):
        backend.response = httpx.Response(401, json={"detail": "nope"})
        body = client.post("/login", data=CREDENTIALS).text
        assert 'value="mark"' in body
        assert "hunter2" not in body

    def test_an_unreachable_backend_shows_a_readable_message(self, client):
        def refuse(request):
            raise httpx.ConnectError(REFUSED, request=request)

        client.app.state.backend._transport = httpx.MockTransport(refuse)
        body = client.post("/login", data=CREDENTIALS).text
        assert "not responding" in body


class TestSignup:
    def test_a_good_signup_redirects_to_the_account_page(self, client):
        response = client.post("/signup", data=CREDENTIALS)
        assert response.status_code == 303
        assert response.headers["location"] == f"/account/{MARK_ID}"

    def test_a_taken_username_re_renders_with_the_backends_message(
        self, client, backend
    ):
        backend.response = httpx.Response(
            409, json={"detail": "username already taken"}
        )
        response = client.post("/signup", data=CREDENTIALS)
        assert response.status_code == 200
        assert "username already taken" in response.text


class TestAccountPage:
    def test_the_page_shows_the_username(self, client):
        assert "mark" in client.get(f"/account/{MARK_ID}").text

    def test_the_page_offers_the_edit_form_and_the_delete_button(self, client):
        body = client.get(f"/account/{MARK_ID}").text
        assert f'hx-post="/account/{MARK_ID}"' in body
        assert f'action="/account/{MARK_ID}/delete"' in body

    def test_an_unknown_account_goes_back_to_the_login_page(self, client, backend):
        backend.response = httpx.Response(404, json={"detail": "user not found"})
        response = client.get(f"/account/{MARK_ID}")
        assert response.status_code == 303
        assert response.headers["location"] == "/"


class TestAccountEdit:
    def test_a_saved_change_swaps_the_form_back_in(self, client):
        response = client.post(f"/account/{MARK_ID}", data={"password": "new"})
        assert response.status_code == 200
        assert "Saved." in response.text

    def test_a_blank_field_is_not_sent(self, client, backend):
        """An empty password box means "leave it alone", not "set it to ''"."""
        client.post(f"/account/{MARK_ID}", data={"username": "m", "password": ""})
        assert backend.body == {"username": "m"}

    def test_two_blank_fields_do_not_reach_the_backend_at_all(self, client, backend):
        response = client.post(
            f"/account/{MARK_ID}", data={"username": "", "password": ""}
        )
        assert backend.requests == []
        assert "Nothing to change." in response.text

    def test_the_form_shows_the_username_the_backend_stored(self, client, backend):
        """Not the one that was typed -- the page must not claim a change the
        backend did not make."""
        backend.response = httpx.Response(200, json={"id": MARK_ID, "username": "m"})
        body = client.post(f"/account/{MARK_ID}", data={"username": "typed"}).text
        assert 'value="m"' in body

    def test_a_rejected_change_shows_the_error_and_keeps_the_form(
        self, client, backend
    ):
        backend.response = httpx.Response(
            409, json={"detail": "username already taken"}
        )
        body = client.post(f"/account/{MARK_ID}", data={"username": "ada"}).text
        assert "username already taken" in body
        assert "hx-post" in body


class TestDelete:
    def test_delete_redirects_to_the_login_page(self, client, backend):
        response = client.post(f"/account/{MARK_ID}/delete")
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert backend.requests == [("DELETE", f"/users/{MARK_ID}")]

    def test_a_failed_delete_stays_on_the_account_page_with_the_error(
        self, client, backend
    ):
        backend.response = httpx.Response(503, json={"detail": "unavailable"})
        response = client.post(f"/account/{MARK_ID}/delete")
        assert response.status_code == 200
        assert "unavailable" in response.text
