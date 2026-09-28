from __future__ import annotations

import pytest
from rag_service.config import Settings


def test_settings_from_env_accepts_zero_minimum_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0")
    monkeypatch.setenv("RAG_MEDIUM_RELEVANCE_SCORE", "0.5")
    monkeypatch.setenv("RAG_HIGH_RELEVANCE_SCORE", "1")

    settings = Settings.from_env()

    assert settings.min_relevance_score == 0
    assert settings.medium_relevance_score == 0.5
    assert settings.high_relevance_score == 1


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RAG_PORT", "65536"),
        ("RAG_MIN_RELEVANCE_SCORE", "-0.1"),
        ("RAG_HIGH_RELEVANCE_SCORE", "1.1"),
    ],
)
def test_settings_reject_invalid_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError):
        Settings.from_env()


def test_settings_reject_unordered_thresholds() -> None:
    with pytest.raises(ValueError):
        Settings(
            min_relevance_score=0.8,
            medium_relevance_score=0.5,
            high_relevance_score=0.9,
        )


def test_settings_reject_overlap_as_large_as_chunk() -> None:
    with pytest.raises(ValueError):
        Settings(chunk_chars=100, chunk_overlap_chars=100)
