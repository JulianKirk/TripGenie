"""Fixtures for the user frontend tests.

The backend is a `MockTransport` rather than the real service: what these tests
are about is the translation in both directions -- form fields into the JSON
bodies the backend documents, and the JSON back into HTML. The real
backend/database pair is already exercised in tests/e2e.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from frontend_service.app import create_app
from frontend_service.config import Settings

MARK_ID = "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
MARK = {"id": MARK_ID, "username": "mark"}


class FakeBackend:
    """Records what it was sent and answers with whatever `response` is set to,
    or the happy path when that is None."""

    def __init__(self):
        self.requests: list[tuple[str, str]] = []
        self.body: dict | None = None
        self.response: httpx.Response | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.content:
            self.body = json.loads(request.content)
        if self.response is not None:
            return self.response
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST" and request.url.path == "/users":
            return httpx.Response(201, json=MARK)
        return httpx.Response(200, json=MARK)


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def client(backend):
    app = create_app(
        Settings(backend_url="http://backend.test"),
        transport=httpx.MockTransport(backend.handle),
    )
    # follow_redirects off: what a POST answers with *is* the assertion in most
    # of these tests, and following it would hide the 303.
    with TestClient(app, follow_redirects=False) as client:
        yield client
