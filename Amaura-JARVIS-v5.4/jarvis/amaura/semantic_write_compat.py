"""Narrow write-grammar compatibility for the Phase 9 semantic core.

This adapter only normalizes a legacy public form where both the target path and
payload are explicitly present but the payload is unquoted, e.g.:

    Create a text file at 'note.txt' containing exactly this text: hello world

It does not infer output roles from path order and does not authorize effects by
itself; authorization remains owned by SemanticRequestGraph/EffectAuthorizer.
"""

from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def _unwrap_classmethod(value: Any) -> Any:
    return getattr(value, "__func__", value)


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


def install_semantic_write_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import semantic_core as core

    current_parse = _unwrap_classmethod(core.SemanticParser.parse)

    def parse_with_unquoted_create_payload(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        normalized = text
        match = re.match(
            r"^\s*create\s+(?:a\s+)?(?:text\s+)?file\s+at\s+"
            r"(?P<q>['\"`])(?P<path>[^'\"`\n]+)(?P=q)\s+"
            r"containing\s+(?:exactly\s+)?(?:this\s+)?text\s*:\s*"
            r"(?P<payload>.+?)\s*$",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            path = match.group("path")
            payload = match.group("payload")
            delimiter = "`" if "`" not in payload else "'"
            normalized = f'Create "{path}" containing {delimiter}{payload}{delimiter}'
        graph = current_parse(cls, normalized, known_extensions)
        graph.original_text = text
        return graph

    _install_attr(core.SemanticParser, "parse", classmethod(parse_with_unquoted_create_payload))
    _INSTALLED = True
