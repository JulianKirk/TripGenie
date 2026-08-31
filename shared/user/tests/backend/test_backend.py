"""Public API tests. Covers the contract in
shared/user/docs/backend-service-api.md.
"""

from __future__ import annotations

from uuid import uuid4

import httpx

from tests.backend.conftest import MARK_ID

PATH = "/users"
BAD_CREDENTIALS = "invalid username or password"
REFUSED = "connection refused"


class TestHealth:
    def test_health_is_ok_when_the_database_service_answers(self, client):
        body = client.get("/health").json()
        assert body == {
            "status": "ok",
            "service": "shared-user-backend",
            "database": "ok",
        }

    def test_health_is_degraded_and_still_200_when_the_database_is_down(
        self, client, database
    ):
        database.response = httpx.Response(500)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["database"] == "unreachable"


class TestLogin:
    def test_the_right_password_answers_with_the_id_and_username(self, client):
        response = client.post(
            f"{PATH}/login", json={"username": "mark", "password": "hunter2"}
        )
        assert response.status_code == 200
        assert response.json() == {"id": MARK_ID, "username": "mark"}

    def test_the_wrong_password_is_401(self, client):
        response = client.post(
            f"{PATH}/login", json={"username": "mark", "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == BAD_CREDENTIALS

    def test_an_unknown_username_is_401_with_the_same_message(self, client, database):
        """Same answer both ways, so the endpoint cannot be used to find out
        which usernames exist."""
        database.users = []
        response = client.post(
            f"{PATH}/login", json={"username": "nobody", "password": "hunter2"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == BAD_CREDENTIALS

    def test_the_password_is_never_in_the_response(self, client):
        response = client.post(
            f"{PATH}/login", json={"username": "mark", "password": "hunter2"}
        )
        assert "password" not in response.text

    def test_login_looks_the_username_up_exactly_once(self, client, database):
        client.post(f"{PATH}/login", json={"username": "mark", "password": "hunter2"})
        assert database.requests == [("GET", "/internal/users")]


class TestCreate:
    def test_signup_answers_201(self, client):
        response = client.post(PATH, json={"username": "mark", "password": "hunter2"})
        assert response.status_code == 201
        assert response.json() == {"id": MARK_ID, "username": "mark"}

    def test_a_taken_username_passes_the_409_through(self, client, database):
        database.response = httpx.Response(
            409, json={"detail": "username already taken"}
        )
        response = client.post(PATH, json={"username": "mark", "password": "x"})
        assert response.status_code == 409
        assert response.json()["detail"] == "username already taken"

    def test_a_missing_password_is_400(self, client):
        assert client.post(PATH, json={"username": "mark"}).status_code == 400


class TestGet:
    def test_get_omits_the_password_the_database_service_sent(self, client):
        """The database service's message carries it; this service's does not,
        so it stops here."""
        response = client.get(f"{PATH}/{MARK_ID}")
        assert response.json() == {"id": MARK_ID, "username": "mark"}

    def test_an_unknown_id_passes_the_404_through(self, client, database):
        database.response = httpx.Response(404, json={"detail": "user not found"})
        response = client.get(f"{PATH}/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "user not found"


class TestUpdate:
    def test_only_the_fields_that_were_sent_are_forwarded(self, client, database):
        client.put(f"{PATH}/{MARK_ID}", json={"password": "new"})
        assert database.body == {"password": "new"}

    def test_an_explicit_null_is_not_forwarded(self, client, database):
        """exclude_none: the database service forbids unknown fields and would
        otherwise be asked to set a field to null."""
        client.put(f"{PATH}/{MARK_ID}", json={"username": "m", "password": None})
        assert database.body == {"username": "m"}

    def test_the_updated_user_comes_back_without_a_password(self, client):
        response = client.put(f"{PATH}/{MARK_ID}", json={"username": "m"})
        assert "password" not in response.json()


class TestDelete:
    def test_delete_answers_204(self, client):
        assert client.delete(f"{PATH}/{MARK_ID}").status_code == 204


class TestUpstreamFailures:
    def test_an_unreachable_database_service_is_503(self, client, database):
        def refuse(request):
            raise httpx.ConnectError(REFUSED, request=request)

        client.app.state.db._client._transport = httpx.MockTransport(refuse)
        response = client.get(f"{PATH}/{MARK_ID}")
        assert response.status_code == 503
        assert response.json()["detail"] == "database service unavailable"

    def test_a_500_from_the_database_service_is_502(self, client, database):
        database.response = httpx.Response(500)
        response = client.get(f"{PATH}/{MARK_ID}")
        assert response.status_code == 502
        assert response.json()["detail"] == "bad response from database service"

    def test_a_response_that_does_not_fit_the_message_is_502(self, client, database):
        database.response = httpx.Response(200, json={"id": "not-a-uuid"})
        assert client.get(f"{PATH}/{MARK_ID}").status_code == 502
