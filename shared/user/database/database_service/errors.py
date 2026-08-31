"""Error handling for the user database service.

Two remaps, both so the backend sees what ../../docs/database-service-api.md
documents:

- FastAPI answers a schema violation with 422; the doc says 400.
- A duplicate username surfaces as SQLAlchemy's `IntegrityError` on commit; the
  doc says 409.

Both keep FastAPI's `{"detail": ...}` body -- the doc lists status codes only,
so there is no error envelope to match.

The 409 is registered here rather than guarded in the route because POST and
PUT can both collide, and a read-then-write check would be a race besides. The
UNIQUE constraint is the one place that can answer correctly, so this is the
one place that translates its answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

USERNAME_TAKEN = "username already taken"


async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # jsonable_encoder because a failing model_validator puts the raw
    # ValueError in ctx, which json.dumps cannot serialise.
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": jsonable_encoder(exc.errors())},
    )


async def integrity_error_handler(
    _request: Request, _exc: IntegrityError
) -> JSONResponse:
    # ponytail: the only constraint on the only table is the username's, so
    # every IntegrityError is that one. Inspect `exc.orig` to tell them apart
    # if a second constraint ever lands.
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": USERNAME_TAKEN}
    )


def register(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
