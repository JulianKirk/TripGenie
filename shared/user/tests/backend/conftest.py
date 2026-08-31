"""Fixtures for the user backend tests.

The database service is a `MockTransport` rather than the real thing: what
these tests are about is this service's own behaviour -- the login comparison,
what it forwards, and what it refuses to put in a response. The real
backend/database pair is exercised in tests/e2e.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend_service.app import create_app
from backend_service.config import Settings

MARK_ID = "3f1c8b52-8f8e-4a3d-9f2e-0b7c1d9a4e11"
MARK = {"id": MARK_ID, "username": "mark", "password": "hunter2"}


class FakeDatabase:
    """Answers like the database service, and records what it was sent so a
    test can assert on the request rather than only the response."""

    def __init__(self):
        self.requests: list[tuple[str, str]] = []
        self.body: dict | None = None
        # What GET /internal/users answers with. Empty is "no such username".
        self.users = [MARK]
        self.response: httpx.Response | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.content:
            self.body = json.loads(request.content)
        if self.response is not None:
            return self.response
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and request.url.path == "/internal/users":
            return httpx.Response(200, json={"users": self.users, "total": 1})
        if request.method == "POST":
            return httpx.Response(201, json={"id": MARK_ID, "username": "mark"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=MARK)


@pytest.fixture
def database():
    return FakeDatabase()


@pytest.fixture
def client(database):
    app = create_app(
        Settings(database_url="http://database.test"),
        transport=httpx.MockTransport(database.handle),
    )
    with TestClient(app) as client:
        yield client
