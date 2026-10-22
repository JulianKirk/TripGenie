"""Client for the shared host-run Multi-Agent Server (Release 2).

The server runs the Planner -> Worker -> Reviewer workflow in the background
and holds each run until a human decides; this client only starts runs, reads
them and forwards the decision. Run records come back as plain dicts because
the server owns their shape; `agent_runs` turns them into this service's view.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable

_FIELD = "multi_agent"
# Server errors worth passing on: each tells the caller something it can act on.
PRESERVED_ERRORS = {
    404: {"RUN_NOT_FOUND"},
    409: {"RUN_NOT_AWAITING_REVIEW"},
    422: {"VALIDATION_ERROR"},
    503: {"RUN_LIMIT_REACHED"},
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
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/runs", body)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/runs/{run_id}")

    def review(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/runs/{run_id}/review", body)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, json=body)
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                "The Multi-Agent Server timed out.",
                [{"field": _FIELD, "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                "The Multi-Agent Server is unavailable.",
                [{"field": _FIELD, "issue": "connection failed"}],
            ) from exc

        if response.is_error:
            _raise_upstream_error(response)
        try:
            data = response.json()["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise _malformed() from exc
        if not isinstance(data, dict):
            raise _malformed()
        return data


def _malformed() -> ApiError:
    return bad_gateway(
        "The Multi-Agent Server returned an invalid response.",
        [{"field": _FIELD, "issue": "response did not match the run contract"}],
    )


def _raise_upstream_error(response: httpx.Response) -> None:
    try:
        error = response.json()["error"]
        code = str(error["code"])
        message = str(error["message"])
        details = [
            {"field": str(item["field"]), "issue": str(item["issue"])}
            for item in error.get("details") or []
        ]
    except (ValueError, KeyError, TypeError):
        code, message, details = "", "", []
    if code in PRESERVED_ERRORS.get(response.status_code, set()):
        raise ApiError(
            status_code=response.status_code,
            code=code,
            message=message,
            details=details or [{"field": _FIELD, "issue": code.lower()}],
        )
    raise bad_gateway(
        "The Multi-Agent Server returned an invalid response.",
        [{"field": _FIELD, "issue": f"unexpected HTTP {response.status_code}"}],
    )
