"""Client for the shared host-run Multi-Agent Server (Release 2).

Modelled on multi_agent_service.client.MultiAgentClient (services integrate
over HTTP, so it is copied rather than imported). Every reply is validated
against the run record contract; the server's runs are asynchronous, so each
call here is short and never waits for the Planner -> Worker -> Reviewer
workflow to finish.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import (
    ApiError,
    bad_gateway,
    dependency_timeout,
    dependency_unavailable,
    validation_error,
)
from .models import MultiAgentRun

FIELD = "multi_agent"
NAME = "The multi-agent planner"
# Upstream errors worth keeping: they tell the caller what to do next. Other
# statuses mean this service and the server disagree about the contract.
PRESERVED_ERRORS = {
    409: {"RUN_NOT_AWAITING_REVIEW"},
    503: {"RUN_LIMIT_REACHED"},
}
MESSAGES = {
    "RUN_NOT_AWAITING_REVIEW": "This plan is no longer awaiting a decision.",
    "RUN_LIMIT_REACHED": f"{NAME} is busy; try again in a moment.",
}


class MultiAgentClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=settings.multi_agent_base_url,
            timeout=httpx.Timeout(settings.multi_agent_timeout_seconds, connect=3.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def start(self, payload: dict[str, Any]) -> MultiAgentRun:
        headers = {"X-Request-ID": str(payload["correlation_id"])}
        return self._run(
            self._request("POST", "/runs", json=payload, headers=headers),
            expected=202,
        )

    def get(self, run_id: str) -> MultiAgentRun:
        return self._run(self._request("GET", f"/runs/{run_id}"), expected=200)

    def review(self, run_id: str, payload: dict[str, Any]) -> MultiAgentRun:
        response = self._request("POST", f"/runs/{run_id}/review", json=payload)
        if response.status_code == 422:
            # The decision itself was refused (for example a correction the
            # run's schema rejects); the run is still awaiting a decision.
            raise validation_error(
                f"{NAME} rejected this decision.",
                _upstream_details(response),
            )
        return self._run(response, expected=200)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                f"{NAME} timed out.",
                [{"field": FIELD, "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                f"{NAME} is unavailable.",
                [{"field": FIELD, "issue": "connection failed"}],
            ) from exc

    def _run(self, response: httpx.Response, *, expected: int) -> MultiAgentRun:
        if response.status_code != expected:
            _raise_upstream_error(response)
        try:
            return MultiAgentRun.model_validate(response.json()["data"])
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise bad_gateway(
                f"{NAME} returned an invalid response.",
                [{"field": FIELD, "issue": "response did not match the run contract"}],
            ) from exc


def _error_code(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return ""


def _upstream_details(response: httpx.Response) -> list[dict[str, str]]:
    try:
        details = response.json()["error"]["details"]
        return [
            {"field": str(detail["field"])[:120], "issue": str(detail["issue"])[:300]}
            for detail in details[:10]
        ] or [{"field": FIELD, "issue": "decision rejected"}]
    except (ValueError, KeyError, TypeError):
        return [{"field": FIELD, "issue": "decision rejected"}]


def _raise_upstream_error(response: httpx.Response) -> None:
    code = _error_code(response)
    if response.status_code == 404 and code == "RUN_NOT_FOUND":
        raise ApiError(
            status_code=404,
            code="NOT_FOUND",
            message="That multi-agent plan was not found.",
            details=[{"field": "run_id", "issue": "resource does not exist"}],
        )
    if code in PRESERVED_ERRORS.get(response.status_code, set()):
        raise ApiError(
            status_code=response.status_code,
            code=code,
            message=MESSAGES[code],
            details=[{"field": FIELD, "issue": code.lower().replace("_", " ")}],
        )
    raise bad_gateway(
        f"{NAME} returned an invalid response.",
        [{"field": FIELD, "issue": f"unexpected HTTP {response.status_code}"}],
    )
