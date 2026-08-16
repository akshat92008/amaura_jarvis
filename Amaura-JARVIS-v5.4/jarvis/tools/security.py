"""Fail-closed filesystem boundary for local tool execution."""

from __future__ import annotations

import contextlib
import contextvars
import os
from collections.abc import Iterator
from pathlib import Path

_WORKSPACE: contextvars.ContextVar[Path | None] = contextvars.ContextVar("jarvis_tool_workspace", default=None)

_SENSITIVE_PARTS = frozenset(
    {
        ".ssh",
        ".aws",
        ".azure",
        ".gnupg",
        ".kube",
        "keychains",
        "secrets",
        ".audit_keys",
        "authority_keys",
        ".config/gcloud",
        ".docker",
    }
)
_SENSITIVE_NAMES = frozenset(
    {
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        "known_hosts",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "dockerconfigjson",
        "service-account.json",
        "audit_hmac_key",
        "authority.key",
        "audit.key",
        "master.key",
    }
)
_SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")
_SYSTEM_ROOTS = ("/etc", "/System", "/private/etc", "/var/root")


def _configured_workspace() -> Path:
    current = _WORKSPACE.get()
    if current is not None:
        return current
    configured = os.environ.get("JARVIS_WORKSPACE_ROOT", "").strip()
    return Path(configured or Path.cwd()).expanduser().resolve()


@contextlib.contextmanager
def tool_workspace(path: str | Path) -> Iterator[Path]:
    root = Path(path).expanduser().resolve()
    token = _WORKSPACE.set(root)
    try:
        yield root
    finally:
        _WORKSPACE.reset(token)


def workspace_root() -> Path:
    return _configured_workspace()


def _is_sensitive(path: Path) -> bool:
    resolved_str = str(path.resolve(strict=False))
    if any(resolved_str == root or resolved_str.startswith(f"{root}/") for root in _SYSTEM_ROOTS):
        return True
    lowered_parts = tuple(part.lower() for part in path.parts)
    if any(part in _SENSITIVE_PARTS for part in lowered_parts):
        return True
    name = path.name.lower()
    if name in _SENSITIVE_NAMES:
        return True
    if name == ".env" or (name.startswith(".env.") and not name.endswith(_SAFE_ENV_SUFFIXES)):
        return True
    if name.endswith((".pem", ".key", ".p12", ".pfx")):
        return True
    return False


def resolve_workspace_path(
    raw_path: str | Path,
    *,
    must_exist: bool = False,
    allow_sensitive: bool = False,
) -> Path:
    root = workspace_root()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path escapes approved workspace: {raw_path}") from exc
    if not allow_sensitive and _is_sensitive(candidate):
        raise PermissionError(f"Sensitive path is blocked: {raw_path}")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(str(candidate))
    return candidate


_PATH_ARGUMENTS = frozenset(
    {
        "path",
        "file_path",
        "directory",
        "cwd",
        "root_dir",
        "repo_path",
        "project_path",
        "workspace",
        "source_path",
        "destination_path",
        "output_path",
    }
)


def secure_tool_arguments(name: str, args: dict) -> dict:
    """Resolve filesystem arguments inside the active workspace before dispatch."""
    secured = dict(args)
    for key, value in list(secured.items()):
        if key not in _PATH_ARGUMENTS:
            continue
        if isinstance(value, str) and value.strip():
            # Some document tools intentionally use a bare output filename. It
            # is still resolved under the workspace rather than the user's home.
            secured[key] = str(resolve_workspace_path(value, must_exist=False))
        elif isinstance(value, list):
            secured[key] = [
                str(resolve_workspace_path(item, must_exist=False)) if isinstance(item, str) and item.strip() else item
                for item in value
            ]
    # git_commit publishes its path collection as ``files`` rather than a
    # singular path argument, so normalize it explicitly.
    if name == "git_commit" and isinstance(secured.get("files"), list):
        secured["files"] = [str(resolve_workspace_path(item, must_exist=False)) for item in secured["files"]]
    return secured


__all__ = [
    "resolve_workspace_path",
    "secure_tool_arguments",
    "tool_workspace",
    "workspace_root",
]
