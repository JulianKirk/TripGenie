"""Release 1: the transport guide page, through the real backend to a fake RAG."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from student3_frontend_service.app import create_app as create_frontend_app
from student3_frontend_service.config import Settings as FrontendSettings

from tests.frontend.conftest import _build_backend

CITATION = {
    "source_id": "transport-pricing-and-costs",
    "path": "ai-services/rag-server/knowledge/transport/pricing-and-costs.md",
    "title": "Transport Pricing and Cost Estimates",
    "section": "Transport pricing: per traveller and per vehicle",
    "chunk_id": "transport-pricing-and-costs:0002",
    "excerpt": "A per-vehicle price is charged once for the whole party.",
}


INSUFFICIENT_ANSWER = "There is not enough indexed context to answer this question."


class FakeRag:
    def __init__(self) -> None:
        self.questions: list[str] = []
        self.mode = "grounded"

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.questions.append(body["query"])
        if self.mode == "down":
            return httpx.Response(
                503,
                json={
                    "error": {
                        "code": "DEPENDENCY_UNAVAILABLE",
                        "message": "AI-Mode is unavailable",
                        "details": [],
                    },
                },
            )
        data: dict[str, Any] = {
            "schema_version": "1",
            "run_id": "rag_run_0001",
            "correlation_id": body["correlation_id"],
            "answer": "A car rental is priced per vehicle [1].",
            "confidence_category": "medium",
            "insufficient_context": False,
            "citations": [CITATION],
            "retrieval": {
                "requested_top_k": 5,
                "returned_chunks": 2,
                "maximum_score": 0.74,
            },
        }
        if self.mode == "insufficient":
            data |= {
                "answer": INSUFFICIENT_ANSWER,
                "confidence_category": "insufficient_context",
                "insufficient_context": True,
                "citations": [],
            }
        return httpx.Response(200, json={"data": data})


@pytest.fixture
def fake_rag() -> FakeRag:
    return FakeRag()


@pytest.fixture
def rag_client(
    frontend_settings: FrontendSettings,
    database_path: Path,
    trips_transport: httpx.MockTransport,
    fake_rag: FakeRag,
) -> Iterator[TestClient]:
    for backend_app in _build_backend(
        database_path,
        trips_transport,
        rag_transport=httpx.MockTransport(fake_rag.handle),
    ):
        app = create_frontend_app(
            frontend_settings,
            transport=httpx.ASGITransport(app=backend_app),
        )
        with TestClient(app) as test_client:
            yield test_client


def _collapsed(response: httpx.Response) -> str:
    return " ".join(response.text.split())


def test_guide_page_explains_grounding(rag_client: TestClient) -> None:
    response = rag_client.get("/guide")

    assert response.status_code == 200
    text = _collapsed(response)
    assert "Ask how transport planning works" in text
    assert "Every answer cites its sources" in text
    assert '<textarea id="question"' in text


def test_guide_link_is_in_the_shell_navigation(client: TestClient) -> None:
    assert "Transport guide" in client.get("/").text


def test_a_grounded_answer_shows_citations_and_confidence(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    response = rag_client.post(
        "/guide",
        data={"question": "  How is a car rental priced?  "},
    )

    assert response.status_code == 200
    assert fake_rag.questions == ["How is a car rental priced?"]
    text = _collapsed(response)
    assert "Grounded answer" in text
    assert "A car rental is priced per vehicle [1]." in text
    assert "confidence--medium" in text
    assert "Medium confidence" in text
    assert "Transport Pricing and Cost Estimates" in text
    assert "Transport pricing: per traveller and per vehicle" in text
    assert "A per-vehicle price is charged once for the whole party." in text
    assert CITATION["path"] in text
    assert "2 of 5 chunks used" in text
    assert "student3-rag-" in text


def test_insufficient_context_shows_no_answer_or_sources(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    fake_rag.mode = "insufficient"

    response = rag_client.post("/guide", data={"question": "Best pizza in Rome?"})

    text = _collapsed(response)
    assert "Not enough context" in text
    assert "insufficient context" in text
    assert "no answer was generated" in text
    assert "Grounded answer" not in text
    assert "Sources" not in text


def test_an_unavailable_rag_server_is_explained(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    fake_rag.mode = "down"

    response = rag_client.post("/guide", data={"question": "How is a car priced?"})

    assert response.status_code == 200
    text = _collapsed(response)
    assert "DEPENDENCY_UNAVAILABLE" in text
    assert "Start them on the host" in text


def test_a_blank_question_is_refused_before_rag(
    rag_client: TestClient,
    fake_rag: FakeRag,
) -> None:
    response = rag_client.post("/guide", data={"question": "   "})

    assert "VALIDATION_ERROR" in response.text
    assert fake_rag.questions == []


def test_disabled_rag_is_shown_as_disabled(client: TestClient) -> None:
    response = client.post("/guide", data={"question": "How is a car priced?"})

    assert response.status_code == 200
    text = _collapsed(response)
    assert "RAG_DISABLED" in text
    assert "disabled in this environment" in text
    assert "Browsing, comparing and planning still work" in text
