"""A small synchronous client for the Multi-Agent Server.

Used by the CLI, and the reference a feature backend copies into its own
package (services integrate over HTTP; they never import each other). Every
failure is one `MultiAgentClientError` carrying the server's error code.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

AWAITING_OR_DONE = frozenset({"awaiting_human", "completed", "rejected", "failed"})


class MultiAgentClientError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MultiAgentClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8013",
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=3.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MultiAgentClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start_run(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/runs", json=request)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/runs/{run_id}")

    def review(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/runs/{run_id}/review", json=decision)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/runs/{run_id}/history")

    def list_runs(self, **params: Any) -> list[dict[str, Any]]:
        query = {key: value for key, value in params.items() if value is not None}
        return self._request("GET", "/runs", params=query)

    def export(self, run_id: str, *, markdown: bool = False) -> Any:
        params = {"format": "markdown" if markdown else "json"}
        response = self._send("GET", f"/runs/{run_id}/export", params=params)
        return response.text if markdown else response.json()["data"]

    def wait(
        self,
        run_id: str,
        *,
        poll_seconds: float = 2.0,
        timeout: float = 480.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Poll until the run needs a human or has finished."""
        deadline = time.monotonic() + timeout
        last_updated = None
        while True:
            run = self.get_run(run_id)
            if on_update is not None and run.get("updated_at") != last_updated:
                last_updated = run.get("updated_at")
                on_update(run)
            if run.get("status") in AWAITING_OR_DONE:
                return run
            if time.monotonic() >= deadline:
                raise MultiAgentClientError(
                    code="CLIENT_TIMEOUT",
                    message=(
                        f"Run {run_id} was still {run.get('status')} "
                        f"after {timeout:.0f}s."
                    ),
                )
            time.sleep(poll_seconds)

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise MultiAgentClientError(
                code="DEPENDENCY_TIMEOUT",
                message="The Multi-Agent Server timed out.",
            ) from exc
        except httpx.RequestError as exc:
            raise MultiAgentClientError(
                code="DEPENDENCY_UNAVAILABLE",
                message="The Multi-Agent Server is unavailable.",
            ) from exc
        if response.is_error:
            try:
                error = response.json()["error"]
                code, message = str(error["code"]), str(error["message"])
            except (ValueError, KeyError, TypeError):
                code = "BAD_GATEWAY"
                message = (
                    f"The Multi-Agent Server returned HTTP {response.status_code}."
                )
            raise MultiAgentClientError(code, message, response.status_code)
        return response

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._send(method, path, **kwargs)
        try:
            return response.json()["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MultiAgentClientError(
                code="BAD_GATEWAY",
                message="The Multi-Agent Server returned a malformed response.",
            ) from exc
