"""Repository class for the user microservice.

Wraps a SQLAlchemy Session and exposes plain CRUD/query methods -- callers work
with these instead of touching Session/SQL directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from database_service.models import User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.orm import Session


def _paginate(
    session: Session, stmt: Select, limit: int, offset: int
) -> tuple[list, int]:
    """Run `stmt` windowed, plus a COUNT over the same filters.

    The count has to be a second query -- a window function would need one row
    back to read the total from, and an empty page has none.
    """
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(session.scalars(stmt.limit(limit).offset(offset)))
    return rows, total


def _commit(session: Session) -> None:
    """Commit, rolling back on failure so a shared Session stays usable."""
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        _commit(self.session)
        return user

    def get(self, id: UUID) -> User | None:
        return self.session.get(User, id)

    def delete(self, id: UUID) -> None:
        user = self.get(id)
        if user is not None:
            self.session.delete(user)
            _commit(self.session)

    def search(
        self, username: str | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        """Backs GET /internal/users.

        `username` is an exact match, not a substring: the only caller is the
        backend answering a login, and "the account named mark" must not also
        find "markus". Omit it to list everyone.
        """
        stmt = select(User)
        if username is not None:
            stmt = stmt.where(User.username == username)
        # A window without an ORDER BY is not a stable page -- SQLite may hand
        # back the same row twice across two pages. There is no created_at to
        # order by, so username (unique, so no tie to break) is the order.
        stmt = stmt.order_by(User.username)
        return _paginate(self.session, stmt, limit, offset)
