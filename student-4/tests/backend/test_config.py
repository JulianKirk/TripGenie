from __future__ import annotations

import pytest
from student4_backend_service.config import Settings


@pytest.mark.parametrize(
    ("name", "value", "attribute", "expected"),
    [
        (
            "STUDENT4_BACKEND_AI_MODE_BASE_URL",
            "http://ai.example.test:8006",
            "ai_mode_url",
            "http://ai.example.test:8006",
        ),
        ("STUDENT4_BACKEND_AI_MODE_TIMEOUT_SECONDS", "101", "ai_mode_timeout", 101.0),
        ("STUDENT4_BACKEND_MCP_ENABLED", "true", "assistant_enabled", True),
        ("STUDENT4_BACKEND_MCP_ENABLED", "false", "assistant_enabled", False),
        ("STUDENT4_BACKEND_MCP_TIMEOUT_SECONDS", "211", "agent_timeout", 211.0),
        (
            "STUDENT4_BACKEND_MCP_PROMPT_ASSET",
            "activity_assistant_custom.md",
            "ai_assistant_prompt_asset",
            "activity_assistant_custom.md",
        ),
        (
            "STUDENT4_BACKEND_RAG_BASE_URL",
            "http://rag.example.test:8011",
            "rag_url",
            "http://rag.example.test:8011",
        ),
        ("STUDENT4_BACKEND_RAG_ENABLED", "true", "rag_enabled", True),
        ("STUDENT4_BACKEND_RAG_ENABLED", "false", "rag_enabled", False),
        ("STUDENT4_BACKEND_RAG_TIMEOUT_SECONDS", "131", "rag_timeout", 131.0),
    ],
)
def test_ai_integrations_read_service_scoped_settings(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    attribute: str,
    expected: str | float | bool,
) -> None:
    monkeypatch.setenv(name, value)
    assert getattr(Settings.from_env(), attribute) == expected
