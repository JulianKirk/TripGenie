"""User endpoints.

Every route returns a `schemas.User` with `exclude_none`, so what a response
contains is decided by which fields the handler fills in rather than by a
per-endpoint response class. The ORM to message translation lives on the model
(`to_message` / `from_message` / `update_from`).

A duplicate username is not handled here: the UNIQUE constraint raises on
commit and `errors.py` turns that into the documented 409, once, for both the
routes that can collide.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, Query, Response, status

from database_service.dependencies import SessionDep, get_or_404
from database_service.models import User
from database_service.repository import UserRepository
from database_service.schemas import User as UserMessage
from database_service.schemas import UserCreateRequest, UserQueryResponse

# The `:uuid` convertor keeps /internal/users/{id} matching only well-formed
# UUIDs, so a future sub-resource path cannot be swallowed by it.
router = APIRouter(prefix="/internal/users", tags=["users"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/{id:uuid}", response_model=UserMessage, response_model_exclude_none=True)
def get_user(id: UUID, session: SessionDep) -> UserMessage:
    row = get_or_404(UserRepository(session), id, "user")
    return row.to_message()


@router.get("", response_model=UserQueryResponse, response_model_exclude_none=True)
def list_users(
    session: SessionDep,
    username: str | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> UserQueryResponse:
    """The one filter this service needs, as a query parameter rather than
    student 2's QUERY-with-a-body.

    ponytail: a GET is all one exact-match filter is worth, and it is what the
    backend's login does. Switch to QUERY when there is more than one field to
    send.
    """
    rows, total = UserRepository(session).search(username, limit, offset)
    return UserQueryResponse(users=[row.to_message() for row in rows], total=total)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UserMessage,
    response_model_exclude_none=True,
)
def create_user(payload: UserCreateRequest, session: SessionDep) -> UserMessage:
    user = UserRepository(session).add(User.from_message(payload))
    # Only the fields the caller needs to find the row again -- the password is
    # left out on purpose and `exclude_none` drops it.
    return UserMessage(id=user.id, username=user.username)


@router.put("/{id:uuid}", response_model=UserMessage, response_model_exclude_none=True)
def update_user(id: UUID, payload: UserMessage, session: SessionDep) -> UserMessage:
    users = UserRepository(session)
    user = get_or_404(users, id, "user")
    user.update_from(payload)
    # add() on an already-persistent instance is a no-op plus the commit.
    return users.add(user).to_message()


@router.delete("/{id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(id: UUID, session: SessionDep) -> Response:
    """Idempotent: deleting a user that is already gone is a 204, not a 404.
    The caller asked for the row to not exist, and it does not."""
    UserRepository(session).delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
