"""Versioned system-prompt catalogue for the Amaura workforce."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PROMPT_VERSION = "2026.07.27"
_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def load_prompt_catalogue() -> dict[str, str]:
    """Load the founder-approved fenced prompts from the individual markdown files."""
    catalogue = {}
    if not _PROMPTS_DIR.exists():
        return catalogue
    
    for file in _PROMPTS_DIR.glob("*.md"):
        # The key is just the filename without the .md extension
        key = file.stem
        catalogue[key] = file.read_text(encoding="utf-8").strip()
        
    return catalogue


def get_system_prompt(role: str, fallback: str) -> str:
    """Return the specified role prompt from the loaded catalogue or the provided fallback."""
    return load_prompt_catalogue().get(role, fallback)


__all__ = ["PROMPT_VERSION", "get_system_prompt", "load_prompt_catalogue"]
