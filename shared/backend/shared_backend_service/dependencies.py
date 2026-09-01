"""Shared route dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from shared_backend_service.client import DatabaseClient


def get_db(request: Request) -> DatabaseClient:
    """The one client, built once in the app lifespan. It pools connections,
    so sharing it is the point -- do not build one per request."""
    return request.app.state.db


DbDep = Annotated[DatabaseClient, Depends(get_db)]
