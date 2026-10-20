from __future__ import annotations

from dataclasses import dataclass, field

ErrorDetails = list[dict[str, str]]

VALIDATION_ERROR_MESSAGE = "One or more fields failed validation."


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: ErrorDetails = field(default_factory=list)


def validation_error(message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message, details or [])


def not_found(run_id: str) -> ApiError:
    return ApiError(
        404,
        "RUN_NOT_FOUND",
        f"Run '{run_id}' was not found.",
        [{"field": "run_id", "issue": "unknown run"}],
    )


def conflict(code: str, message: str, details: ErrorDetails | None = None) -> ApiError:
    return ApiError(409, code, message, details or [])


def busy(limit: int) -> ApiError:
    return ApiError(
        503,
        "RUN_LIMIT_REACHED",
        "The Multi-Agent Server is already running its maximum number of workflows.",
        [{"field": "runs", "issue": f"at most {limit} active runs"}],
    )


class AgentError(Exception):
    """A stage failed: the run records it and stops, keeping earlier steps."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
