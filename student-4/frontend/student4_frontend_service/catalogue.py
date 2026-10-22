"""Catalogue context shared by browsing and inline assistant responses."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .errors import FrontendError
from .models import TripDirectory
from .query import QueryInputError, build_search_body

if TYPE_CHECKING:
    from fastapi import Request

    from .client import BackendClient
    from .models import CategoryList


def _error(exc: BaseException, fallback: str) -> str:
    return exc.detail if isinstance(exc, FrontendError) else fallback


def _category_labels(categories: CategoryList | BaseException) -> dict[str, str]:
    if isinstance(categories, BaseException):
        return {}
    return {row.code: row.label for row in categories.categories}


def _results_context(
    *,
    page: object,
    labels: dict[str, str],
    params: object,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "page": page if not isinstance(page, BaseException) else None,
        "labels": labels,
        "params": params,
        "error": error,
        "party_size": getattr(params, "get", lambda _name: None)("party_size"),
    }


async def catalogue_context(
    request: Request, client: BackendClient
) -> dict[str, object]:
    try:
        body = build_search_body(request.query_params)
    except QueryInputError as exc:
        body = {"limit": 20, "offset": 0}
        query_error: str | None = str(exc)
    else:
        query_error = None
    body["include_inactive"] = True
    categories, page, trips = await asyncio.gather(
        client.categories(), client.search(body), client.trips(), return_exceptions=True
    )
    labels = _category_labels(categories)
    results_error = query_error
    if isinstance(page, BaseException):
        results_error = _error(page, "Activities could not be loaded.")
    return {
        "categories": None if isinstance(categories, BaseException) else categories,
        "selected_limit": body["limit"],
        "categories_error": (
            _error(categories, "Categories could not be loaded.")
            if isinstance(categories, BaseException)
            else None
        ),
        "trip_directory": (
            TripDirectory(available=False, trips=[])
            if isinstance(trips, BaseException)
            else trips
        ),
        **_results_context(
            page=page,
            labels=labels,
            params=request.query_params,
            error=results_error,
        ),
    }
