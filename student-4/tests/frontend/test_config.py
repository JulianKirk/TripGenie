from __future__ import annotations

import pytest
from student4_frontend_service.config import Settings


def test_settings_use_documented_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.delenv("BACKEND_TIMEOUT", raising=False)
    monkeypatch.delenv("AI_TIMEOUT", raising=False)

    settings = Settings.from_env()

    assert settings.backend_url == "http://student-4-backend:8008"
    assert settings.backend_timeout == 5.0
    assert settings.ai_timeout == 210.0
    assert settings.service_name == "student-4-frontend"


def test_settings_normalise_backend_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_URL", "https://backend.example.test/")

    assert Settings.from_env().backend_url == "https://backend.example.test"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "backend.test",
        "ftp://backend.test",
        "https://backend.test/prefix",
        "https://user:secret@backend.test",
        "https://backend.test?debug=true",
        "https://backend.test#fragment",
    ],
)
def test_settings_reject_invalid_backend_url(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("BACKEND_URL", value)

    with pytest.raises(ValueError, match="BACKEND_URL"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["zero", "0", "-1"])
def test_settings_reject_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("BACKEND_TIMEOUT", value)

    with pytest.raises(ValueError, match="BACKEND_TIMEOUT"):
        Settings.from_env()


def test_settings_parse_a_separate_ai_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_TIMEOUT", "4")
    monkeypatch.setenv("AI_TIMEOUT", "175")

    settings = Settings.from_env()

    assert settings.backend_timeout == 4
    assert settings.ai_timeout == 175
