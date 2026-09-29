from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_error
from .models import RagAnswer

FEATURE = "student-5"
TOP_K = 5
PRESERVED_ERRORS = {
    503: {"INDEX_NOT_READY", "DEPENDENCY_UNAVAILABLE"},
    504: {"DEPENDENCY_TIMEOUT"},
}
MESSAGES = {
    "INDEX_NOT_READY": "The knowledge index is not ready.",
    "DEPENDENCY_UNAVAILABLE": "The knowledge assistant is unavailable.",
    "DEPENDENCY_TIMEOUT": "The knowledge assistant timed out.",
}


class RagClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=settings.rag_base_url,
            timeout=httpx.Timeout(settings.rag_timeout_seconds, connect=3.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def query(self, question: str, correlation_id: str) -> RagAnswer:
        try:
            response = self._client.post(
                "/query",
                json={
                    "query": question,
                    "feature": FEATURE,
                    "top_k": TOP_K,
                    "correlation_id": correlation_id,
                },
            )
        except httpx.TimeoutException as exc:
            raise ApiError(
                504,
                "DEPENDENCY_TIMEOUT",
                MESSAGES["DEPENDENCY_TIMEOUT"],
                [{"field": "rag", "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_error("rag", "connection failed") from exc

        if response.is_error:
            self._raise_upstream_error(response)

        try:
            payload: Any = response.json()["data"]
            if payload.get("schema_version") != "1":
                raise ValueError("unsupported schema version")
            return RagAnswer.model_validate(payload)
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ValidationError,
        ) as exc:
            raise bad_gateway("rag", "response did not match the RAG contract") from exc

    @staticmethod
    def _raise_upstream_error(response: httpx.Response) -> None:
        try:
            code = str(response.json()["error"]["code"])
        except (ValueError, KeyError, TypeError):
            code = ""
        if code in PRESERVED_ERRORS.get(response.status_code, set()):
            raise ApiError(
                response.status_code,
                code,
                MESSAGES[code],
                [{"field": "rag", "issue": code.lower().replace("_", " ")}],
            )
        raise bad_gateway("rag", f"unexpected HTTP {response.status_code}")
