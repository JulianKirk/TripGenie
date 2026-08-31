"""User microservice ORM models.

One table, described in ../../user-service.md. The table also owns the
translation to and from the wire messages in `schemas.py` -- `to_message`,
`from_message` and `update_from` below. A row knows how to describe itself; the
routers just call these.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from database_service import schemas


class Base(DeclarativeBase):
    """Declarative base every ORM model in this service inherits from."""


class User(Base):
    """An account. A username to log in with and a password to prove it."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # The login handle, and the only identity this service has. UNIQUE is what
    # makes "that username is taken" a database answer rather than a read
    # followed by a racy write -- see errors.py, which turns the IntegrityError
    # into the documented 409.
    username: Mapped[str] = mapped_column(unique=True)
    # ponytail: the password, in plaintext, compared with ==. Deliberate for
    # this release -- the compose network is the trust boundary and there is
    # nothing here worth stealing. Upgrade path is one column and two call
    # sites: store `hashlib.scrypt(password, salt=...)` in a `password_hash`
    # column and compare with `hmac.compare_digest` in the backend's login
    # route.
    password: Mapped[str]

    @classmethod
    def from_message(cls, message: schemas.UserCreateRequest) -> User:
        """A new row from a create request. The request type is the strict
        subclass, so the fields read here are guaranteed present."""
        return cls(username=message.username, password=message.password)

    def update_from(self, message: schemas.User) -> None:
        """Apply an edit. Only fields the caller actually sent are touched, so
        an omitted field is left alone. An explicit `null` does not clear a
        field either: PUT is documented as a merge, and neither field has a
        meaningful empty value.
        """
        for field in message.model_fields_set - {"id"}:
            value = getattr(message, field)
            if value is not None:
                setattr(self, field, value)

    def to_message(self) -> schemas.User:
        """The full row as a message, password included.

        The backend service is the only caller and needs it to answer a login.
        The *backend's* own `User` message has no password field, so it never
        reaches a browser.
        """
        return schemas.User.model_validate(self)
