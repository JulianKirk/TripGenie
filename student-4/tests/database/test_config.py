"""Configuration parsing tests."""

import pytest
from student4_database_service.config import DEFAULT_DATABASE_URL, Settings


def test_settings_use_documented_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SEED_DATA", raising=False)

    settings = Settings.from_env()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.seed is True
    assert settings.service_name == "student-4-database"


def test_settings_parse_disabled_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom.db")
    monkeypatch.setenv("SEED_DATA", "false")

    settings = Settings.from_env()

    assert settings.database_url == "sqlite:///custom.db"
    assert settings.seed is False


def test_settings_reject_unknown_seed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_DATA", "sometimes")

    with pytest.raises(ValueError, match="SEED_DATA"):
        Settings.from_env()
