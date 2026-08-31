"""User endpoints -- the public account surface.

Most of these wrap the matching endpoint on the database service; the client
turns anything unusable into the documented 502/503 and passes a 4xx through
unchanged, so those bodies stay one line. `login` is the only route with logic
of its own.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003  (FastAPI reads this at runtime)

from fastapi import APIRouter, HTTPException, Response, status

from backend_service.client import parse
from backend_service.dependencies import DbDep  # noqa: TC001  (runtime)
from backend_service.schemas import (
    LoginRequest,
    User,
    UserCreateRequest,
    UserUpdateRequest,
)

# The `:uuid` convertor keeps /users/{id} matching only well-formed UUIDs, so a
# future sub-resource path cannot be swallowed by it.
router = APIRouter(prefix="/users", tags=["users"])

# One message for both failures. Telling a caller which half was wrong tells
# them which usernames exist, and it does not help someone who typed their own
# password wrong.
BAD_CREDENTIALS = "invalid username or password"


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=User,
    response_model_exclude_none=True,
)
async def create_user(payload: UserCreateRequest, db: DbDep) -> User:
    """Sign up. A taken username is the database service's 409, passed through
    by the client untouched."""
    return parse(User, await db.create(payload.model_dump(mode="json")))


@router.post("/login", response_model=User, response_model_exclude_none=True)
async def login(payload: LoginRequest, db: DbDep) -> User:
    """Who this is, if the password matches.

    ponytail: no session, no token, no cookie. The answer is the id, and the
    frontend puts it in the URL. Whoever holds a user id is that user until
    this grows a real session -- issue a signed cookie here when it does.
    """
    body = await db.by_username(payload.username)
    users = body.get("users") if isinstance(body, dict) else None
    if not users:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
    # username is UNIQUE, so there is at most one.
    found = users[0]
    # ponytail: `!=` on plaintext, matching how the password is stored. Becomes
    # `hmac.compare_digest` against a hash when models.py grows one.
    if found.get("password") != payload.password:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
    return parse(User, found)


@router.get("/{id:uuid}", response_model=User, response_model_exclude_none=True)
async def get_user(id: UUID, db: DbDep) -> User:
    return parse(User, await db.get(id))


@router.put("/{id:uuid}", response_model=User, response_model_exclude_none=True)
async def update_user(id: UUID, payload: UserUpdateRequest, db: DbDep) -> User:
    # exclude_none because the database service forbids unknown fields and
    # would otherwise be asked to set a field to null. Send only what the
    # caller actually set.
    body = payload.model_dump(mode="json", exclude_none=True)
    return parse(User, await db.update(id, body))


@router.delete("/{id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(id: UUID, db: DbDep) -> Response:
    await db.delete(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
