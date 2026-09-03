"""Request-scoped dependencies shared by the database routes."""

from __future__ import annotations

from collections.abc import Iterator  # noqa: TC003  (FastAPI reads this at runtime)
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    request.app.state.ensure_database_initialized()
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
