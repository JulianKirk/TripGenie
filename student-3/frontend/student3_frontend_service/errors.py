from __future__ import annotations

from dataclasses import dataclass, field

ErrorDetails = list[dict[str, str]]


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: ErrorDetails = field(default_factory=list)


def bad_gateway(message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(
        status_code=502,
        code="BAD_GATEWAY",
        message=message,
        details=details or [],
    )


def dependency_timeout(message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(
        status_code=504,
        code="DEPENDENCY_TIMEOUT",
        message=message,
        details=details or [],
    )


def dependency_unavailable(
    message: str,
    details: ErrorDetails | None = None,
) -> ApiError:
    return ApiError(
        status_code=503,
        code="DEPENDENCY_UNAVAILABLE",
        message=message,
        details=details or [],
    )


def validation_error(message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(
        status_code=422,
        code="VALIDATION_ERROR",
        message=message,
        details=details or [],
    )
