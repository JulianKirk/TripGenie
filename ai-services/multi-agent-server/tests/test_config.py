from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from multi_agent_service.config import DEFAULT_FEATURES, Settings

if TYPE_CHECKING:
    from pathlib import Path

ENV = [
    "MULTI_AGENT_HOST",
    "MULTI_AGENT_PORT",
    "MULTI_AGENT_AI_MODE_URL",
    "MULTI_AGENT_MODEL",
    "MULTI_AGENT_DB_PATH",
    "MULTI_AGENT_FEATURES",
    "MULTI_AGENT_RUN_TIMEOUT_SECONDS",
    "MULTI_AGENT_MAX_REVISIONS",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_a_local_host_service() -> None:
    settings = Settings.from_env()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8013
    assert settings.ai_mode_base_url == "http://127.0.0.1:8006"
    assert settings.model is None
    assert settings.features == DEFAULT_FEATURES
    assert settings.max_revisions == 1
    assert settings.db_path.name == "runs.sqlite3"


def test_settings_are_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MULTI_AGENT_PORT", "8113")
    monkeypatch.setenv("MULTI_AGENT_AI_MODE_URL", "http://127.0.0.1:9006/")
    monkeypatch.setenv("MULTI_AGENT_MODEL", "qwen2.5:0.5b")
    monkeypatch.setenv("MULTI_AGENT_DB_PATH", str(tmp_path / "x.sqlite3"))
    monkeypatch.setenv("MULTI_AGENT_FEATURES", "student-3, student-5")
    monkeypatch.setenv("MULTI_AGENT_MAX_REVISIONS", "0")

    settings = Settings.from_env()

    assert settings.port == 8113
    assert settings.ai_mode_base_url == "http://127.0.0.1:9006"
    assert settings.model == "qwen2.5:0.5b"
    assert settings.db_path == tmp_path / "x.sqlite3"
    assert settings.features == ("student-3", "student-5")
    assert settings.max_revisions == 0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("MULTI_AGENT_PORT", "eighty", "whole number"),
        ("MULTI_AGENT_PORT", "70000", "at most 65535"),
        ("MULTI_AGENT_AI_MODE_URL", "ftp://ai", "valid HTTP"),
        ("MULTI_AGENT_FEATURES", " , ", "at least one feature"),
        ("MULTI_AGENT_FEATURES", "Student 3", "invalid name"),
        ("MULTI_AGENT_RUN_TIMEOUT_SECONDS", "0", "greater than zero"),
        ("MULTI_AGENT_RUN_TIMEOUT_SECONDS", "30", "cover at least one"),
        ("MULTI_AGENT_MAX_REVISIONS", "3", "at most 2"),
    ],
)
def test_invalid_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        Settings.from_env()
