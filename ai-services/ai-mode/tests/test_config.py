from __future__ import annotations

from pathlib import Path

import pytest

from ai_mode_service.config import DEFAULT_OLLAMA_BASE_URL, Settings


@pytest.fixture
def clear_ai_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "AI_MODE_SERVICE_NAME",
        "AI_MODE_OLLAMA_BASE_URL",
        "AI_MODE_DEFAULT_MODEL",
        "AI_MODE_ALLOWED_MODELS",
        "AI_MODE_TIMEOUT_SECONDS",
        "AI_MODE_MAX_PROMPT_CHARS",
        "AI_MODE_MAX_SCHEMA_CHARS",
        "AI_MODE_MAX_RESPONSE_BYTES",
    ):
        monkeypatch.delenv(env_name, raising=False)


def test_settings_default_to_host_ollama_loopback(
    clear_ai_mode_env: None,
) -> None:
    settings = Settings.from_env()

    assert settings.ollama_base_url == DEFAULT_OLLAMA_BASE_URL


def test_settings_accept_host_docker_internal_override_for_containers(
    clear_ai_mode_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AI_MODE_OLLAMA_BASE_URL",
        "http://host.docker.internal:11434",
    )

    settings = Settings.from_env()

    assert settings.ollama_base_url == "http://host.docker.internal:11434"


def test_dockerfile_does_not_pin_ollama_provider_topology() -> None:
    dockerfile_path = Path(__file__).resolve().parents[1] / "Dockerfile"
    dockerfile = dockerfile_path.read_text(encoding="utf-8")

    assert "AI_MODE_OLLAMA_BASE_URL=" not in dockerfile
