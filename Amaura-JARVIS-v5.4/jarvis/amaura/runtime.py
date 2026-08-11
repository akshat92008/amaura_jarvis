"""Local runtime configuration helpers for Amaura.

The workforce intentionally avoids a mandatory dotenv dependency. This module
loads a small, strictly parsed ``.env.amaura`` file before the control plane or
HTTP server reads operational settings.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Iterable

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOADED_FILES: set[Path] = set()


def _candidate_files(explicit: str | Path | None = None) -> Iterable[Path]:
    if explicit is None and os.environ.get("AMAURA_SKIP_ENV_AUTOLOAD") == "1":
        return
    seen: set[Path] = set()
    values: list[Path] = []
    configured = explicit or os.environ.get("AMAURA_ENV_FILE", "")
    if configured:
        values.append(Path(configured).expanduser())
    values.extend(
        [
            Path.cwd() / ".env.amaura",
            Path(__file__).resolve().parents[2] / ".env.amaura",
            Path.home() / ".amaura" / ".env.amaura",
        ]
    )
    for value in values:
        resolved = value.resolve()
        if resolved not in seen:
            seen.add(resolved)
            yield resolved


def _decode_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise ValueError("unterminated quoted value")
        value = value[1:-1]
        if quote == '"':
            value = (
                value.replace(r"\n", "\n")
                .replace(r"\r", "\r")
                .replace(r"\t", "\t")
                .replace(r'\"', '"')
                .replace(r"\\", "\\")
            )
    return value


def load_amaura_env(
    path: str | Path | None = None,
    *,
    override: bool = False,
    require_private_permissions: bool = False,
) -> Path | None:
    """Load the first available Amaura env file without executing shell code.

    Existing process environment values win unless ``override`` is explicitly
    requested. On POSIX, launch tooling can require mode ``0600`` (or stricter).
    """

    if path is None and os.environ.get("AMAURA_SKIP_ENV_FILE", "0") == "1":
        return None

    for candidate in _candidate_files(path):
        if not candidate.is_file():
            continue
        if candidate in _LOADED_FILES and not override:
            return candidate
        if require_private_permissions and os.name == "posix":
            permissions = stat.S_IMODE(candidate.stat().st_mode)
            if permissions & 0o077:
                raise PermissionError(
                    f"Amaura environment file must not be group/world accessible: {candidate}"
                )
        for line_number, raw_line in enumerate(
            candidate.read_text(encoding="utf-8", errors="strict").splitlines(),
            start=1,
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                raise ValueError(
                    f"Invalid environment assignment at {candidate}:{line_number}"
                )
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if not _ENV_KEY.fullmatch(key):
                raise ValueError(
                    f"Invalid environment key at {candidate}:{line_number}: {key!r}"
                )
            if override or not os.environ.get(key):
                os.environ[key] = _decode_value(raw_value)
        _LOADED_FILES.add(candidate)
        return candidate
    return None


__all__ = ["load_amaura_env"]
