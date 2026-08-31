"""End-to-end tests for the HTTP layer, driven through TestClient against a
real (temporary) SQLite file -- the same path the container takes, minus the
network. Covers the contract in shared/user/docs/database-service-api.md.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

MARK = {"username": "mark", "password": "hunter2"}
PATH = "/internal/users"


@pytest.fixture
def mark_id(client):
    return client.post(PATH, json=MARK).json()["id"]


class TestHealth:
    def test_health_reports_ok_and_names_the_service(self, client):
        body = client.get("/health").json()
        assert body == {"status": "ok", "service": "shared-user-database"}


class TestCreate:
    def test_create_answers_201_with_the_id_and_username(self, client):
        response = client.post(PATH, json=MARK)
        assert response.status_code == 201
        assert response.json().keys() == {"id", "username"}

    def test_create_does_not_echo_the_password(self, client):
        assert "password" not in client.post(PATH, json=MARK).json()

    def test_a_duplicate_username_is_409(self, client, mark_id):
        response = client.post(PATH, json=MARK)
        assert response.status_code == 409
        assert response.json()["detail"] == "username already taken"

    def test_a_missing_password_is_400(self, client):
        assert client.post(PATH, json={"username": "mark"}).status_code == 400

    def test_an_empty_username_is_400(self, client):
        payload = {"username": "", "password": "x"}
        assert client.post(PATH, json=payload).status_code == 400

    def test_an_unknown_field_is_400(self, client):
        payload = {**MARK, "admin": True}
        assert client.post(PATH, json=payload).status_code == 400


class TestGet:
    def test_get_returns_the_whole_user_including_the_password(self, client, mark_id):
        body = client.get(f"{PATH}/{mark_id}").json()
        assert body == {"id": mark_id, "username": "mark", "password": "hunter2"}

    def test_an_unknown_id_is_404(self, client):
        response = client.get(f"{PATH}/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "user not found"

    def test_a_malformed_id_does_not_reach_the_handler(self, client):
        assert client.get(f"{PATH}/not-a-uuid").status_code == 404


class TestList:
    def test_username_filter_finds_the_one_user(self, client, mark_id):
        body = client.get(PATH, params={"username": "mark"}).json()
        assert body["total"] == 1
        assert body["users"][0]["id"] == mark_id

    def test_an_unknown_username_is_an_empty_page_not_a_404(self, client, mark_id):
        response = client.get(PATH, params={"username": "nobody"})
        assert response.status_code == 200
        assert response.json() == {"users": [], "total": 0}

    def test_without_a_filter_everyone_is_listed(self, client, mark_id):
        client.post(PATH, json={"username": "ada", "password": "x"})
        assert client.get(PATH).json()["total"] == 2


class TestUpdate:
    def test_a_password_change_leaves_the_username_alone(self, client, mark_id):
        body = client.put(f"{PATH}/{mark_id}", json={"password": "new"}).json()
        assert body["username"] == "mark"
        assert body["password"] == "new"

    def test_a_username_change_leaves_the_password_alone(self, client, mark_id):
        body = client.put(f"{PATH}/{mark_id}", json={"username": "m"}).json()
        assert body["password"] == "hunter2"

    def test_renaming_onto_a_taken_username_is_409(self, client, mark_id):
        client.post(PATH, json={"username": "ada", "password": "x"})
        response = client.put(f"{PATH}/{mark_id}", json={"username": "ada"})
        assert response.status_code == 409

    def test_updating_an_unknown_id_is_404(self, client):
        response = client.put(f"{PATH}/{uuid4()}", json={"username": "x"})
        assert response.status_code == 404


class TestDelete:
    def test_delete_answers_204_and_the_user_is_gone(self, client, mark_id):
        assert client.delete(f"{PATH}/{mark_id}").status_code == 204
        assert client.get(f"{PATH}/{mark_id}").status_code == 404

    def test_deleting_an_unknown_id_is_still_204(self, client):
        """The caller asked for the row to not exist, and it does not."""
        assert client.delete(f"{PATH}/{uuid4()}").status_code == 204

    def test_the_username_is_free_again_after_a_delete(self, client, mark_id):
        client.delete(f"{PATH}/{mark_id}")
        assert client.post(PATH, json=MARK).status_code == 201
