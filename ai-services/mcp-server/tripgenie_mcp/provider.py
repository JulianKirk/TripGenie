"""Bounded read-only access to the five public backend APIs."""

import httpx


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class ProviderClient:
    def __init__(
        self, urls: dict[str, str], transport: httpx.BaseTransport | None = None
    ):
        self.urls = urls
        self.client = httpx.Client(
            transport=transport, timeout=httpx.Timeout(30.0, connect=3.0)
        )

    def close(self) -> None:
        self.client.close()

    def read(
        self,
        owner: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        query: dict[str, object] | None = None,
    ) -> object:
        try:
            response = self.client.request(
                "QUERY" if query is not None else "GET",
                self.urls[owner] + path,
                params=params,
                json=query,
            )
            if response.status_code == 404:
                raise ProviderError("NOT_FOUND", "Resource not found")
            if response.status_code in (400, 422):
                raise ProviderError("VALIDATION_ERROR", "Provider rejected the request")
            if response.status_code >= 500:
                raise ProviderError("PROVIDER_UNAVAILABLE", "Provider failed", True)
            if response.status_code != 200 or len(response.content) > 65536:
                raise ProviderError("INVALID_RESPONSE", "Unexpected provider response")
            payload = response.json()
            if owner in ("student-1", "student-3", "student-5"):
                if not isinstance(payload, dict) or "data" not in payload:
                    raise ProviderError("INVALID_RESPONSE", "Missing provider data")
                return payload["data"]
            if not isinstance(payload, dict):
                raise ProviderError("INVALID_RESPONSE", "Invalid provider data")
            return payload
        except httpx.TimeoutException as exc:
            raise ProviderError("PROVIDER_TIMEOUT", "Provider timed out", True) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                "PROVIDER_UNAVAILABLE", "Provider unreachable", True
            ) from exc
        except ValueError as exc:
            raise ProviderError("INVALID_RESPONSE", "Invalid provider JSON") from exc
