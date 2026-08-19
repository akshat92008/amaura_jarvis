#!/usr/bin/env python3
"""Compatibility entrypoint for the retired V7 company LaunchAgent installer.

The old command is kept only so existing local scripts fail safely into the
single ARCH deployment path. It can no longer install
``jarvis.amaura.company_daemon`` or create a second scheduler service.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jarvis.arch_macos_service import DEFAULT_LABEL, LEGACY_LABELS, launch_agent_payload
from scripts import install_arch_launchd as _arch

LABEL = DEFAULT_LABEL
LEGACY_LABEL = LEGACY_LABELS[0]


def _payload(repo_root: Path, *, poll_seconds: float = 30.0) -> dict:
    """Compatibility helper returning only the canonical ARCH payload."""
    _ = poll_seconds
    try:
        return launch_agent_payload(repo_root)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc


def install(repo_root: Path, *, poll_seconds: float = 30.0, dry_run: bool = False) -> int:
    """Install the canonical ARCH service; legacy cadence flags are ignored."""
    _ = poll_seconds
    return _arch.install(repo_root, dry_run=dry_run)


def uninstall(repo_root: Path, *, dry_run: bool = False) -> int:
    """Remove ARCH and any legacy split-runtime LaunchAgents."""
    return _arch.uninstall(repo_root, dry_run=dry_run)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper: manage the canonical ARCH LaunchAgent"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--poll-seconds", type=float, default=30.0, help="Ignored compatibility option")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(args.repo_root)
    if args.install:
        return install(repo_root, poll_seconds=args.poll_seconds, dry_run=args.dry_run)
    return uninstall(repo_root, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
