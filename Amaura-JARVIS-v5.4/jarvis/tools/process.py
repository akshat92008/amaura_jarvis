"""Shell-free process helpers for legacy local tools."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterable
from pathlib import Path

_SHELL_META = re.compile(r"[\x00-\x1f;&|<>`$]")
_GIT_REV = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@{}~^:+-]{0,255}")


def parse_command_argv(command: str) -> list[str]:
    """Parse a simple command without invoking a shell.

    Pipelines, redirects, substitutions, control operators and control
    characters are deliberately unsupported.  Consequential execution should
    use the governed Docker sandbox instead of this legacy compatibility path.
    """
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    if _SHELL_META.search(command):
        raise ValueError("shell operators, substitutions and control characters are not allowed")
    argv = shlex.split(command, posix=os.name != "nt")
    if not argv:
        raise ValueError("command produced no executable")
    if argv[0].startswith("-"):
        raise ValueError("command executable cannot begin with '-'")
    return argv


def validate_git_revision(revision: str) -> str:
    if not isinstance(revision, str):
        raise ValueError("git revision must be a string")
    revision = revision.strip()
    if not revision:
        return ""
    if revision.startswith("-") or _SHELL_META.search(revision) or not _GIT_REV.fullmatch(revision):
        raise ValueError("invalid or unsafe Git revision")
    return revision


def repo_relative_path(raw: str | Path, cwd: str | Path) -> str:
    root = Path(cwd).expanduser().resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path escapes repository: {raw}") from exc
    return relative.as_posix() or "."


def ensure_safe_tokens(values: Iterable[str], *, label: str) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} entries must be non-empty strings")
        if _SHELL_META.search(value):
            raise ValueError(f"unsafe characters in {label} entry")
        result.append(value)
    return result


__all__ = ["ensure_safe_tokens", "parse_command_argv", "repo_relative_path", "validate_git_revision"]
