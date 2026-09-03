"""Documented FastAPI error mappings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details = []
    for error in exc.errors():
        location = ".".join(
            str(part) for part in error["loc"] if part not in {"body", "query", "path"}
        )
        details.append(f"{location or 'request'}: {error['msg']}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "; ".join(details)},
    )


async def database_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, SQLAlchemyError):
        raise exc
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "database operation failed"},
    )


def register(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
