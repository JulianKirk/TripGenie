from __future__ import annotations

from typing import Any

import httpx


class BackendError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str = "BACKEND_UNAVAILABLE",
        details: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details or []


class BackendClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=5.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def ready(self) -> bool:
        try:
            return self._client.get("/ready").status_code == 200
        except httpx.RequestError:
            return False

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, f"/api/v1{path}", **kwargs)
        except httpx.RequestError as exc:
            raise BackendError("The budget service is currently unavailable.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendError(
                "The budget service returned an invalid response."
            ) from exc

        if response.is_error:
            error = payload.get("error", {})
            raise BackendError(
                str(error.get("message", "The request could not be completed.")),
                status_code=response.status_code,
                code=str(error.get("code", "BACKEND_ERROR")),
                details=error.get("details", []),
            )

        if "data" not in payload:
            raise BackendError("The budget service returned an invalid response.")
        return payload["data"]