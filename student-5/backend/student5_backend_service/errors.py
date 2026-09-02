from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: list[dict[str, str]] = field(default_factory=list)


def dependency_error(dependency: str, issue: str) -> ApiError:
    return ApiError(
        503,
        "DEPENDENCY_UNAVAILABLE",
        f"The {dependency} service is unavailable.",
        [{"field": dependency, "issue": issue}],
    )


def bad_gateway(dependency: str, issue: str) -> ApiError:
    return ApiError(
        502,
        "INVALID_DEPENDENCY_RESPONSE",
        f"The {dependency} service returned an invalid response.",
        [{"field": dependency, "issue": issue}],
    )


def invalid_trip(trip_id: str) -> ApiError:
    return ApiError(
        422,
        "VALIDATION_ERROR",
        "The trip does not exist.",
        [{"field": "trip_id", "issue": f"trip '{trip_id}' was not found"}],
    )


def date_outside_trip() -> ApiError:
    return ApiError(
        422,
        "VALIDATION_ERROR",
        "The expense date must fall within the trip dates.",
        [{"field": "date", "issue": "must fall within the trip dates"}],
    )
