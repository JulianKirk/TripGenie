"""Repository tests -- the CRUD and the one lookup, against a real Session."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from database_service.models import User
from database_service.schemas import User as UserMessage
from database_service.schemas import UserCreateRequest


class TestUserRepository:
    def test_added_user_can_be_fetched_by_id(self, users, mark):
        assert users.get(mark.id) is mark

    def test_get_returns_none_for_an_unknown_id(self, users):
        assert users.get(uuid4()) is None

    def test_delete_removes_the_user(self, users, mark):
        users.delete(mark.id)
        assert users.get(mark.id) is None

    def test_delete_is_a_no_op_for_an_unknown_id(self, users):
        users.delete(uuid4())  # must not raise

    def test_a_duplicate_username_is_rejected(self, users, mark):
        with pytest.raises(IntegrityError):
            users.add(User(username="mark", password="something-else"))


class TestSearch:
    def test_search_without_a_username_lists_everyone(self, users, mark, ada):
        rows, total = users.search(None, limit=20, offset=0)
        assert total == 2
        assert [row.username for row in rows] == ["ada", "mark"]

    def test_search_by_username_is_an_exact_match(self, users, mark):
        rows, total = users.search("mark", limit=20, offset=0)
        assert total == 1
        assert rows[0].id == mark.id

    def test_a_prefix_of_a_username_matches_nothing(self, users, mark):
        assert users.search("mar", limit=20, offset=0) == ([], 0)

    def test_an_unknown_username_matches_nothing(self, users, mark):
        assert users.search("nobody", limit=20, offset=0) == ([], 0)


class TestMessages:
    def test_from_message_builds_a_row_from_a_create_request(self):
        message = UserCreateRequest(username="grace", password="cobol")
        user = User.from_message(message)
        assert (user.username, user.password) == ("grace", "cobol")

    def test_to_message_carries_the_password(self, mark):
        """The backend needs it to answer a login. Its own message drops it."""
        assert mark.to_message().password == "hunter2"

    def test_update_from_changes_only_what_was_sent(self, mark):
        mark.update_from(UserMessage(password="new-secret"))
        assert (mark.username, mark.password) == ("mark", "new-secret")

    def test_update_from_ignores_a_field_that_was_not_sent(self, mark):
        mark.update_from(UserMessage(username="mark-two"))
        assert mark.password == "hunter2"

    def test_update_from_will_not_change_the_id(self, mark):
        original = mark.id
        mark.update_from(UserMessage(id=uuid4(), username="renamed"))
        assert mark.id == original
