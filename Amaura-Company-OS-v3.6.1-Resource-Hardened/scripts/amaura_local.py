#!/usr/bin/env python3
"""Backward-compatible wrapper for the canonical ``amaura`` operator CLI."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from jarvis.amaura.cli import main  # noqa: E402


def _translate(arguments: list[str]) -> list[str]:
    if not arguments:
        return arguments
    aliases = {
        "once": ["worker", "--once"],
        "drain": ["worker", "--drain"],
        "start": ["worker"],
    }
    return [*aliases.get(arguments[0], [arguments[0]]), *arguments[1:]]


if __name__ == "__main__":
    raise SystemExit(main(_translate(sys.argv[1:])))
