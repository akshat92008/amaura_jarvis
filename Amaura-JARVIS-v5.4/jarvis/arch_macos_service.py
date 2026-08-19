"""Canonical macOS LaunchAgent support for the single ARCH runtime.

The plist contains no credentials. ARCH loads the mode-0600 private environment
file after launch and owns company autonomy, missions, cognition, HUD/API and
configured remote surfaces inside one process.
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path
from typing import Any

DEFAULT_LABEL = "com.amaura.arch"
LEGACY_LABELS = ("com.amaura.jarvis.company", "com.amaura.company-os")


def _runtime_paths(repository_root: str | Path) -> tuple[Path, Path, Path, Path]:
    root = Path(repository_root).expanduser().resolve()
    python = root / ".venv" / "bin" / "python"
    env_file = root / ".env.amaura"
    logs = Path.home() / ".jarvis" / "logs"
    return root, python, env_file, logs


def _require_canonical_label(label: str) -> str:
    clean = str(label).strip()
    if clean != DEFAULT_LABEL:
        raise ValueError(f"ARCH runtime label is fixed to {DEFAULT_LABEL}")
    return DEFAULT_LABEL


def launch_agent_payload(
    repository_root: str | Path,
    *,
    label: str = DEFAULT_LABEL,
) -> dict[str, Any]:
    """Return the one canonical credential-free ARCH LaunchAgent payload."""
    label = _require_canonical_label(label)
    root, python, env_file, logs = _runtime_paths(repository_root)
    if not python.is_file():
        raise FileNotFoundError(f"ARCH virtualenv Python is missing: {python}")
    if not env_file.is_file():
        raise FileNotFoundError(f"ARCH private environment file is missing: {env_file}")
    if os.name == "posix" and env_file.stat().st_mode & 0o077:
        raise PermissionError(f"ARCH environment file must be private (chmod 600): {env_file}")
    return {
        "Label": label,
        "ProgramArguments": [
            str(python),
            "-m",
            "jarvis.arch",
            "--env-file",
            str(env_file),
            "--headless",
            "--no-web",
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "arch.out.log"),
        "StandardErrorPath": str(logs / "arch.err.log"),
    }


def write_launch_agent(
    repository_root: str | Path,
    *,
    destination: str | Path | None = None,
    label: str = DEFAULT_LABEL,
) -> Path:
    """Write the canonical ARCH plist with private permissions."""
    label = _require_canonical_label(label)
    root, _python, _env_file, logs = _runtime_paths(repository_root)
    payload = launch_agent_payload(root, label=label)
    path = (
        Path(destination).expanduser().resolve()
        if destination
        else Path.home() / "Library" / "LaunchAgents" / f"{DEFAULT_LABEL}.plist"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(plistlib.dumps(payload, sort_keys=True))
    if os.name == "posix":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name == "posix":
        path.chmod(0o600)
    return path


__all__ = ["DEFAULT_LABEL", "LEGACY_LABELS", "launch_agent_payload", "write_launch_agent"]
