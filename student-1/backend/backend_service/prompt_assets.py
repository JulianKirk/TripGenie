from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources

PROMPT_DIRECTORY = "prompts"
PROMPT_ASSET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$")
PROMPT_ASSET_ERROR = (
    "STUDENT1_BACKEND_AI_PROMPT_ASSET must name a markdown file inside "
    "backend_service/prompts without path separators or traversal."
)


def validate_prompt_asset(prompt_asset: str) -> str:
    asset_name = _normalise_prompt_asset_name(prompt_asset)
    load_prompt_asset(asset_name)
    return asset_name


@lru_cache(maxsize=16)
def load_prompt_asset(prompt_asset: str) -> str:
    asset_name = _normalise_prompt_asset_name(prompt_asset)
    prompt_root = resources.files("backend_service").joinpath(PROMPT_DIRECTORY)
    prompt_path = prompt_root.joinpath(asset_name)
    try:
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(
            "STUDENT1_BACKEND_AI_PROMPT_ASSET "
            f"'{asset_name}' was not found in backend_service/prompts."
        ) from exc
    except OSError as exc:
        raise ValueError(
            "STUDENT1_BACKEND_AI_PROMPT_ASSET "
            f"'{asset_name}' could not be read from backend_service/prompts."
        ) from exc


def _normalise_prompt_asset_name(prompt_asset: str) -> str:
    asset_name = prompt_asset.strip()
    if not asset_name:
        raise ValueError("STUDENT1_BACKEND_AI_PROMPT_ASSET must not be blank.")
    if PROMPT_ASSET_PATTERN.fullmatch(asset_name) is None:
        raise ValueError(PROMPT_ASSET_ERROR)
    return asset_name
