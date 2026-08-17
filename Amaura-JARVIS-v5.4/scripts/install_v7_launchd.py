#!/usr/bin/env python3
"""Install/uninstall the Amaura v7 company daemon as a macOS LaunchAgent.

This installer is intentionally explicit and local-only. It writes no secrets to
the plist; ``amaura-company`` loads the private ``.env.amaura`` file itself.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.amaura.jarvis.company"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Amaura company LaunchAgent")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False, timeout=30)


def _paths(repo_root: Path) -> tuple[Path, Path, Path, Path]:
    home = Path.home()
    plist = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    logs = home / ".jarvis" / "logs"
    stdout = logs / "amaura-company.out.log"
    stderr = logs / "amaura-company.err.log"
    python = repo_root / ".venv" / "bin" / "python"
    return plist, stdout, stderr, python


def _payload(repo_root: Path, *, poll_seconds: float) -> dict:
    plist, stdout, stderr, python = _paths(repo_root)
    del plist
    if not python.is_file():
        raise RuntimeError(f"Amaura virtualenv Python not found: {python}")
    env_file = repo_root / ".env.amaura"
    if not env_file.is_file():
        raise RuntimeError(f"Amaura private environment file not found: {env_file}")
    if os.name == "posix" and env_file.stat().st_mode & 0o077:
        raise RuntimeError(f"Amaura environment file must be private (chmod 600): {env_file}")
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python),
            "-m",
            "jarvis.amaura.company_daemon",
            "--env-file",
            str(env_file),
            "--poll-seconds",
            str(max(5.0, min(float(poll_seconds), 3600.0))),
            "--max-work-units",
            "1",
        ],
        "WorkingDirectory": str(repo_root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(stdout),
        "StandardErrorPath": str(stderr),
    }


def install(repo_root: Path, *, poll_seconds: float, dry_run: bool) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("Amaura LaunchAgent installation is supported only on macOS")
    repo_root = repo_root.expanduser().resolve()
    plist, stdout, stderr, _python = _paths(repo_root)
    payload = _payload(repo_root, poll_seconds=poll_seconds)
    rendered = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)
    if dry_run:
        sys.stdout.buffer.write(rendered)
        return 0

    plist.parent.mkdir(parents=True, exist_ok=True)
    stdout.parent.mkdir(parents=True, exist_ok=True)
    temporary = plist.with_suffix(".plist.tmp")
    temporary.write_bytes(rendered)
    temporary.chmod(0o600)
    os.replace(temporary, plist)
    plist.chmod(0o600)

    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist))
    boot = _launchctl("bootstrap", domain, str(plist))
    if boot.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {boot.stderr.strip()}")
    enable = _launchctl("enable", f"{domain}/{LABEL}")
    if enable.returncode != 0:
        raise RuntimeError(f"launchctl enable failed: {enable.stderr.strip()}")
    kick = _launchctl("kickstart", "-k", f"{domain}/{LABEL}")
    if kick.returncode != 0:
        raise RuntimeError(f"launchctl kickstart failed: {kick.stderr.strip()}")
    print(f"Installed and started {LABEL}: {plist}")
    return 0


def uninstall(repo_root: Path, *, dry_run: bool) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("Amaura LaunchAgent installation is supported only on macOS")
    plist, _stdout, _stderr, _python = _paths(repo_root.expanduser().resolve())
    if dry_run:
        print(f"Would remove {plist}")
        return 0
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist))
    plist.unlink(missing_ok=True)
    print(f"Removed {LABEL}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if shutil.which("launchctl") is None and not args.dry_run:
        raise RuntimeError("launchctl is not available")
    repo_root = Path(args.repo_root)
    if args.install:
        return install(repo_root, poll_seconds=args.poll_seconds, dry_run=args.dry_run)
    return uninstall(repo_root, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
