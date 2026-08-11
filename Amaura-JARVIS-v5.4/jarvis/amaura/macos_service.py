"""macOS LaunchAgent support for the Amaura company runtime.

The generated plist contains no credentials. Amaura loads its mode-0600
`.env.amaura` file inside the governed runtime after launch.
"""

from __future__ import annotations

import argparse
import os
import plistlib
from pathlib import Path
from typing import Any

DEFAULT_LABEL = "com.amaura.company-os"


def launch_agent_payload(
    repository_root: str | Path,
    *,
    label: str = DEFAULT_LABEL,
) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve()
    log_dir = root / ".amaura-data" / "logs"
    return {
        "Label": label,
        "ProgramArguments": ["/bin/zsh", str(root / "Launch_Amaura.command")],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 15,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "launchd.stdout.log"),
        "StandardErrorPath": str(log_dir / "launchd.stderr.log"),
    }


def write_launch_agent(
    repository_root: str | Path,
    *,
    destination: str | Path | None = None,
    label: str = DEFAULT_LABEL,
) -> Path:
    root = Path(repository_root).expanduser().resolve()
    if not (root / "Launch_Amaura.command").is_file():
        raise FileNotFoundError("Launch_Amaura.command is missing from the repository root")
    path = (
        Path(destination).expanduser().resolve()
        if destination
        else Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / ".amaura-data" / "logs").mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(launch_agent_payload(root, label=label), sort_keys=True))
    if os.name == "posix":
        path.chmod(0o600)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Amaura's credential-free macOS LaunchAgent")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--destination", default="")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    args = parser.parse_args()
    path = write_launch_agent(
        args.repository,
        destination=args.destination or None,
        label=args.label,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
