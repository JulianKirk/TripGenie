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