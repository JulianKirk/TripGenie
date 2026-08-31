"""The wire format for the user database service API.

Separate from `models.py`: that is the ORM table, these are the messages
described in ../../docs/database-service-api.md.

One message, nullable fields -- the protobuf convention student 2's services
established. `User` is the PUT body and the response body for every endpoint;
which fields are populated is what differs. Routes serialise with
`response_model_exclude_none=True`, so an unset field is absent from the JSON
rather than an explicit `null`, and "a user with only the id filled in" is a
legal response instead of a mostly-empty object.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """The user message. Every field is nullable because the same class carries
    an edit and a response."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID | None = None
    username: str | None = Field(default=None, min_length=1)
    # Present on this service's messages, absent from the backend's. The
    # backend needs it to answer a login; a browser never does.
    password: str | None = Field(default=None, min_length=1)


class UserCreateRequest(User):
    """POST body. The strict subclass: the two fields a row cannot exist
    without are required here, so `from_message` can read them unconditionally.
    """

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserQueryResponse(BaseModel):
    """A page of users, plus how many matched in total."""

    model_config = ConfigDict(extra="forbid")

    users: list[User]
    total: int


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
