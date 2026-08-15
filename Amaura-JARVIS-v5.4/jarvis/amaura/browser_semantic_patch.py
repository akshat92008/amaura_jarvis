"""Compatibility patch for natural multi-selector browser requests."""
from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def normalize_selector_list(text: str) -> str:
    """Expose each quoted CSS selector to the legacy per-selector grammar.

    The legacy parser understands `selector ".a"` but not the natural form
    `CSS selectors: ".a", ".b"`.  We preserve the original request and append
    explicit selector aliases only for syntactically unambiguous CSS values.
    """
    if not re.search(r"\b(?:css\s+selectors?|selectors?)\b\s*:?", text, re.IGNORECASE):
        return text

    selectors: list[str] = []
    for match in re.finditer(r"['\"]([^'\"\n]+)['\"]", text):
        value = match.group(1).strip()
        if not value:
            continue
        if value.startswith((".", "#", "[")) or any(ch in value for ch in (">", "[", ":")):
            if value not in selectors:
                selectors.append(value)

    if len(selectors) < 2:
        return text

    aliases = " ".join(f'selector "{selector}"' for selector in selectors)
    return f"{text} {aliases}"


def install_browser_semantic_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da

    original_try_browser = da.DirectActionRouter._try_browser_action.__func__

    def patched_try_browser(cls: Any, text: str):
        return original_try_browser(cls, normalize_selector_list(text))

    da.DirectActionRouter._try_browser_action = classmethod(patched_try_browser)
    _INSTALLED = True
