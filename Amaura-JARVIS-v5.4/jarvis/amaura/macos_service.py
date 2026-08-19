"""Canonical macOS LaunchAgent support for the Amaura company runtime.

There is exactly one supported company-runtime service identity. The generated
plist contains no credentials; the daemon loads the mode-0600 ``.env.amaura``
file after launch. Historical callers cannot mint a second scheduler label.
"""

from __future__ import annotations

import argparse
import os
import plistlib
from pathlib import Path
from typing import Any

DEFAULT_LABEL = "com.amaura.jarvis.company"


def _runtime_paths(repository_root: str | Path) -> tuple[Path, Path, Path, Path]:
    root = Path(repository_root).expanduser().resolve()
    python = root / ".venv" / "bin" / "python"
    env_file = root / ".env.amaura"
    logs = Path.home() / ".jarvis" / "logs"
    return root, python, env_file, logs


def _require_canonical_label(label: str) -> str:
    clean = str(label).strip()
    if clean != DEFAULT_LABEL:
        raise ValueError(f"Amaura company runtime label is fixed to {DEFAULT_LABEL}")
    return DEFAULT_LABEL


def launch_agent_payload(
    repository_root: str | Path,
    *,
    label: str = DEFAULT_LABEL,
    poll_seconds: float = 30.0,
) -> dict[str, Any]:
    """Return the one canonical credential-free company LaunchAgent payload."""
    label = _require_canonical_label(label)
    root, python, env_file, logs = _runtime_paths(repository_root)
    if not python.is_file():
        raise FileNotFoundError(f"Amaura virtualenv Python is missing: {python}")
    if not env_file.is_file():
        raise FileNotFoundError(f"Amaura private environment file is missing: {env_file}")
    if os.name == "posix" and env_file.stat().st_mode & 0o077:
        raise PermissionError(f"Amaura environment file must be private (chmod 600): {env_file}")
    delay = max(5.0, min(float(poll_seconds), 3600.0))
    return {
        "Label": label,
        "ProgramArguments": [
            str(python),
            "-m",
            "jarvis.amaura.company_daemon",
            "--env-file",
            str(env_file),
            "--poll-seconds",
            str(delay),
            "--max-work-units",
            "1",
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "amaura-company.out.log"),
        "StandardErrorPath": str(logs / "amaura-company.err.log"),
    }


def write_launch_agent(
    repository_root: str | Path,
    *,
    destination: str | Path | None = None,
    label: str = DEFAULT_LABEL,
    poll_seconds: float = 30.0,
) -> Path:
    """Write the canonical private plist atomically enough for local installation."""
    label = _require_canonical_label(label)
    root, _python, _env_file, logs = _runtime_paths(repository_root)
    payload = launch_agent_payload(root, label=label, poll_seconds=poll_seconds)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Amaura's canonical credential-free macOS LaunchAgent")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--destination", default="")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    args = parser.parse_args()
    path = write_launch_agent(
        args.repository,
        destination=args.destination or None,
        poll_seconds=args.poll_seconds,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DEFAULT_LABEL", "launch_agent_payload", "write_launch_agent"]
