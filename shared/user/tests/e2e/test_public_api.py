"""The whole account lifecycle, through both real services.

One test per journey rather than per endpoint: what is under test here is that
the two services agree, and a journey is what proves it.
"""

from __future__ import annotations

PATH = "/users"
MARK = {"username": "mark", "password": "hunter2"}


class TestAccountLifecycle:
    def test_sign_up_log_in_rename_and_delete(self, client):
        created = client.post(PATH, json=MARK)
        assert created.status_code == 201
        user_id = created.json()["id"]

        signed_in = client.post(f"{PATH}/login", json=MARK)
        assert signed_in.status_code == 200
        assert signed_in.json() == {"id": user_id, "username": "mark"}

        renamed = client.put(f"{PATH}/{user_id}", json={"username": "mark-two"})
        assert renamed.json()["username"] == "mark-two"

        # The rename moved the login handle; the password is untouched.
        assert client.post(f"{PATH}/login", json=MARK).status_code == 401
        moved = {"username": "mark-two", "password": "hunter2"}
        assert client.post(f"{PATH}/login", json=moved).status_code == 200

        assert client.delete(f"{PATH}/{user_id}").status_code == 204
        assert client.get(f"{PATH}/{user_id}").status_code == 404
        assert client.post(f"{PATH}/login", json=moved).status_code == 401

    def test_a_password_change_takes_effect_on_the_next_login(self, client):
        user_id = client.post(PATH, json=MARK).json()["id"]
        client.put(f"{PATH}/{user_id}", json={"password": "new-secret"})

        assert client.post(f"{PATH}/login", json=MARK).status_code == 401
        changed = {"username": "mark", "password": "new-secret"}
        assert client.post(f"{PATH}/login", json=changed).status_code == 200

    def test_a_taken_username_is_409_through_both_services(self, client):
        client.post(PATH, json=MARK)
        response = client.post(PATH, json={"username": "mark", "password": "other"})
        assert response.status_code == 409
        assert response.json()["detail"] == "username already taken"

    def test_no_response_in_the_whole_journey_carries_a_password(self, client):
        """The database service stores and returns one; the public API must
        never repeat it."""
        created = client.post(PATH, json=MARK)
        user_id = created.json()["id"]
        responses = [
            created,
            client.post(f"{PATH}/login", json=MARK),
            client.get(f"{PATH}/{user_id}"),
            client.put(f"{PATH}/{user_id}", json={"password": "new-secret"}),
        ]
        for response in responses:
            assert "hunter2" not in response.text
            assert "new-secret" not in response.text
            assert "password" not in response.text

    def test_health_reports_both_services(self, client):
        body = client.get("/health").json()
        assert body == {
            "status": "ok",
            "service": "shared-user-backend",
            "database": "ok",
        }
