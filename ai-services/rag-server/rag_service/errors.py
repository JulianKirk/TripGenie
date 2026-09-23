from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
    details: list[dict[str, str]] = field(default_factory=list)


def validation_error(details: list[dict[str, str]]) -> ApiError:
    return ApiError(
        422,
        "VALIDATION_ERROR",
        "One or more fields failed validation.",
        details=details,
    )


def bad_gateway(message: str, *, field: str, issue: str) -> ApiError:
    return ApiError(
        502,
        "BAD_GATEWAY",
        message,
        details=[{"field": field, "issue": issue}],
    )


def dependency_unavailable(message: str, *, field: str, issue: str) -> ApiError:
    return ApiError(
        503,
        "DEPENDENCY_UNAVAILABLE",
        message,
        retryable=True,
        details=[{"field": field, "issue": issue}],
    )


def dependency_timeout(message: str, *, field: str, issue: str) -> ApiError:
    return ApiError(
        504,
        "DEPENDENCY_TIMEOUT",
        message,
        retryable=True,
        details=[{"field": field, "issue": issue}],
    )


def index_not_ready(message: str) -> ApiError:
    return ApiError(
        503,
        "INDEX_NOT_READY",
        message,
        details=[{"field": "index", "issue": "build the RAG index before querying"}],
    )
