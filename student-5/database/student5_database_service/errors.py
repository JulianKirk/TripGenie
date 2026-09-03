from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: list[dict[str, str]] = field(default_factory=list)


def not_found(resource: str, resource_id: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{resource} '{resource_id}' was not found.")


def conflict(message: str, field_name: str) -> ApiError:
    return ApiError(
        409, "CONFLICT", message, [{"field": field_name, "issue": "already exists"}]
    )


def invalid_update() -> ApiError:
    return ApiError(
        422,
        "VALIDATION_ERROR",
        "At least one field must be supplied.",
        [{"field": "body", "issue": "must contain at least one field"}],
    )
