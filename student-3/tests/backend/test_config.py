from __future__ import annotations

import pytest
from student3_backend_service.config import Settings


def test_currency_is_normalised_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDENT3_BACKEND_CURRENCY", "aud")

    assert Settings.from_env().currency == "AUD"


def test_invalid_currency_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDENT3_BACKEND_CURRENCY", "dollars")

    with pytest.raises(ValueError, match="3-letter ISO code"):
        Settings.from_env()


def test_mcp_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "STUDENT3_BACKEND_MCP_ENABLED",
        "STUDENT3_BACKEND_MCP_BASE_URL",
        "STUDENT3_BACKEND_MCP_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.mcp_enabled is False
    assert settings.mcp_base_url == "http://127.0.0.1:8012/mcp"
    assert settings.mcp_timeout_seconds == 40.0


def test_mcp_settings_are_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STUDENT3_BACKEND_MCP_ENABLED", "true")
    monkeypatch.setenv(
        "STUDENT3_BACKEND_MCP_BASE_URL",
        "http://host.docker.internal:8012/mcp/",
    )
    monkeypatch.setenv("STUDENT3_BACKEND_MCP_TIMEOUT_SECONDS", "15")

    settings = Settings.from_env()

    assert settings.mcp_enabled is True
    assert settings.mcp_base_url == "http://host.docker.internal:8012/mcp"
    assert settings.mcp_timeout_seconds == 15.0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("STUDENT3_BACKEND_MCP_BASE_URL", "ftp://mcp", "valid HTTP or HTTPS URL"),
        ("STUDENT3_BACKEND_MCP_TIMEOUT_SECONDS", "0", "greater than zero"),
    ],
)
def test_invalid_mcp_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        Settings.from_env()
