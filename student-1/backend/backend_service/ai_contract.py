from __future__ import annotations

import re

AI_MODE_PROMPT_MAX_CHARS_DEFAULT = 12000
AI_MODE_PROMPT_MAX_CHARS_MAX = 12000
MAX_CORRELATION_ID_CHARS = 64
CORRELATION_ID_PATTERN = re.compile(
    rf"^[A-Za-z0-9][A-Za-z0-9._:-]{{0,{MAX_CORRELATION_ID_CHARS - 1}}}$"
)
CORRELATION_ID_ISSUE = (
    "must start with a letter or digit, contain only letters, digits, '.', "
    f"'_', ':', or '-', and be at most {MAX_CORRELATION_ID_CHARS} characters"
)
LOG_VALUE_MAX_CHARS = 160


def validate_correlation_id_value(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    if CORRELATION_ID_PATTERN.fullmatch(cleaned) is None:
        raise ValueError(CORRELATION_ID_ISSUE)
    return cleaned


def sanitise_log_value(value: object, *, max_length: int = LOG_VALUE_MAX_CHARS) -> str:
    text = "None" if value is None else str(value)
    cleaned = "".join(
        character
        if (
            character not in {"\u2028", "\u2029"}
            and ord(character) >= 32
            and ord(character) != 127
        )
        else "?"
        for character in text
    )
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}…"
