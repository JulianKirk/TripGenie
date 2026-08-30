"""Shared route dependencies and helpers.

Everything here is used by more than one router; anything used by exactly one
lives with that router instead.
"""

from __future__ import annotations

from collections.abc import Iterator  # noqa: TC003  (FastAPI reads this at runtime)
from typing import Annotated
from uuid import UUID  # noqa: TC003  (same)

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

NOT_FOUND = "not found"


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, always closed. The engine and session factory
    are built once in the app lifespan and stashed on `app.state`."""
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]

# The pagination pair every list endpoint takes, declared once.
LimitDep = Annotated[int, Query(ge=1, le=100)]
OffsetDep = Annotated[int, Query(ge=0)]


def get_or_404(repository, id: UUID, what: str):
    """Fetch by id or raise the documented 404. `repository` is any of the
    repository classes -- they all expose the same `get(id)`."""
    row = repository.get(id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} {NOT_FOUND}")
    return row
