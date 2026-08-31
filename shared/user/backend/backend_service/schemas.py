"""The wire format for the public user API.

Declared here rather than imported from the database service: the two images
deploy independently, so each owns its copy of the message and drift between
them surfaces as the documented 502 (see `client.parse`) instead of an import
error at build time.

The one real difference from the database service's copy: **`User` has no
`password` field.** A password goes in on a create, a login or an edit and
never comes back out, so there is no shape in which this service can echo one
to a browser.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """The user message, as the public API publishes it. Every field is
    nullable because the same class carries an edit and a response."""

    # `ignore`, not `forbid`, and this is the mechanism that drops the
    # password: the database service's copy of the message carries one, this
    # one has no field for it, and `client.parse` quietly leaves it behind.
    # Forbidding extras here would instead make every upstream response a 502.
    # The request bodies below still forbid them -- an unknown field from a
    # caller is a mistake worth reporting; an extra field from the service that
    # owns the row is not.
    model_config = ConfigDict(extra="ignore")

    id: UUID | None = None
    username: str | None = Field(default=None, min_length=1)


class UserCreateRequest(BaseModel):
    """POST /users -- sign up."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    """POST /users/login. Same fields as a create; a different meaning, and a
    different answer when they do not match anything."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserUpdateRequest(BaseModel):
    """PUT /users/{id} -- change the username, the password, or both. Both are
    optional; whatever is sent is what changes."""

    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=1)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    database: str
