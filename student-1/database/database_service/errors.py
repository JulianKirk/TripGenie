from __future__ import annotations

from dataclasses import dataclass, field

ErrorDetails = list[dict[str, str]]


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: ErrorDetails = field(default_factory=list)


def bad_request(message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(
        status_code=400,
        code="BAD_REQUEST",
        message=message,
        details=details or [],
    )


def not_found(resource: str, resource_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code="NOT_FOUND",
        message=f"{resource} '{resource_id}' was not found.",
        details=[{"field": "id", "issue": "resource does not exist"}],
    )


def conflict(message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(
        status_code=409,
        code="CONFLICT",
        message=message,
        details=details or [],
    )


def validation_error(
    message: str,
    details: ErrorDetails | None = None,
) -> ApiError:
    return ApiError(
        status_code=422,
        code="VALIDATION_ERROR",
        message=message,
        details=details or [],
    )
