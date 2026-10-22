from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_error

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
        return self._run("POST", "/runs", body)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._run("GET", f"/runs/{run_id}")

    def review(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._run("POST", f"/runs/{run_id}/review", body)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/runs/{run_id}/history")
        if not isinstance(data, list):
            raise bad_gateway("multi_agent", "history did not match the contract")
        return [event for event in data if isinstance(event, dict)]

    def _run(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = self._request(method, path, body)
        if not isinstance(data, dict):
            raise bad_gateway("multi_agent", "run did not match the contract")
        return data

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        try:
            response = self._client.request(method, path, json=body)
        except httpx.TimeoutException as exc:
            raise ApiError(
                504,
                "DEPENDENCY_TIMEOUT",
                "The Multi-Agent Server timed out.",
                [{"field": "multi_agent", "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_error("multi_agent", "connection failed") from exc

        if response.is_error:
            self._raise_upstream_error(response)
        try:
            return response.json()["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise bad_gateway(
                "multi_agent", "response did not match the run contract"
            ) from exc

    @staticmethod
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
                response.status_code,
                code,
                message,
                details or [{"field": "multi_agent", "issue": code.lower()}],
            )
        raise bad_gateway("multi_agent", f"unexpected HTTP {response.status_code}")
