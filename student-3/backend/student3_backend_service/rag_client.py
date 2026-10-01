"""Client for the shared host-run RAG server (Release 1).

Ported from Student 1's client (itself ported from Student 5's). The answer,
citations, confidence and insufficient-context state are validated against the
RAG contract and passed through unchanged; nothing here rewrites what the
knowledge base said.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import ApiError, bad_gateway, dependency_timeout, dependency_unavailable
from .models import RagAnswer

FEATURE = "student-3"
TOP_K = 5
# RAG error codes worth keeping: they tell the traveller *why* there is no answer.
PRESERVED_ERRORS = {
    503: {"INDEX_NOT_READY", "DEPENDENCY_UNAVAILABLE"},
    504: {"DEPENDENCY_TIMEOUT"},
}
MESSAGES = {
    "INDEX_NOT_READY": "The transport knowledge index is not ready.",
    "DEPENDENCY_UNAVAILABLE": "The transport knowledge assistant is unavailable.",
    "DEPENDENCY_TIMEOUT": "The transport knowledge assistant timed out.",
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
                headers={"X-Request-ID": correlation_id},
            )
        except httpx.TimeoutException as exc:
            raise dependency_timeout(
                MESSAGES["DEPENDENCY_TIMEOUT"],
                [{"field": "rag", "issue": "request timed out"}],
            ) from exc
        except httpx.RequestError as exc:
            raise dependency_unavailable(
                MESSAGES["DEPENDENCY_UNAVAILABLE"],
                [{"field": "rag", "issue": "connection failed"}],
            ) from exc

        if response.is_error:
            _raise_upstream_error(response)

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
            raise bad_gateway(
                "The transport knowledge assistant returned an invalid response.",
                [{"field": "rag", "issue": "response did not match the RAG contract"}],
            ) from exc


def _raise_upstream_error(response: httpx.Response) -> None:
    try:
        code = str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        code = ""
    if code in PRESERVED_ERRORS.get(response.status_code, set()):
        raise ApiError(
            status_code=response.status_code,
            code=code,
            message=MESSAGES[code],
            details=[{"field": "rag", "issue": code.lower().replace("_", " ")}],
        )
    raise bad_gateway(
        "The transport knowledge assistant returned an invalid response.",
        [{"field": "rag", "issue": f"unexpected HTTP {response.status_code}"}],
    )
