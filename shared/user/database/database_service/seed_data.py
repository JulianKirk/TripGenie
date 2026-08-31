"""Starter accounts, inserted on first start.

The service ships with an empty SQLite file, so without these there is no
account to log in with and the only way onto the account page is to sign up
first. Rows go in through the same `UserCreateRequest` -> `User.from_message`
path a POST takes, so a seed row cannot be shaped differently to a created one.

ponytail: a literal tuple, not a fixtures file or a CLI. It is demo data for
Release 0; delete the module once there is a real import path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from database_service.models import User
from database_service.schemas import UserCreateRequest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SEED_USERS: tuple[dict[str, Any], ...] = (
    {"username": "mark", "password": "hunter2"},
    {"username": "ada", "password": "difference-engine"},
)


def seed(session: Session) -> int:
    """Insert the starter rows if the table is empty. Returns how many went in.

    Empty-only, so a restart against the mounted volume does not duplicate them
    -- which the UNIQUE username would reject anyway -- and does not fight
    whatever a caller has since created or deleted.
    """
    if session.scalar(select(func.count()).select_from(User)):
        return 0
    for payload in SEED_USERS:
        message = UserCreateRequest.model_validate(payload)
        session.add(User.from_message(message))
    session.commit()
    return len(SEED_USERS)
