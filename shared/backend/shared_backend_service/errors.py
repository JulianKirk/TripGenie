"""Error handling for the shared reference backend service.

The API doc specifies 400 for "invalid input / validation error"; FastAPI's
default for a schema violation is 422. This remaps it so a caller sees the
documented status, keeping FastAPI's `{"detail": [...]}` body -- the doc lists
status codes only, so there is no error envelope to match.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # jsonable_encoder because a failing model_validator puts the raw
    # ValueError in ctx, which json.dumps cannot serialise.
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": jsonable_encoder(exc.errors())},
    )


def register(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
