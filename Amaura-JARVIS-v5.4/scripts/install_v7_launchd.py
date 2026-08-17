#!/usr/bin/env python3
"""Install/uninstall the one canonical Amaura company daemon LaunchAgent.

Installation migrates the historical ``com.amaura.company-os`` service only
after the canonical daemon is verified. Any failure after bootstrap rolls the
canonical service back instead of leaving a half-installed scheduler.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from jarvis.amaura.macos_service import DEFAULT_LABEL, launch_agent_payload

LABEL = DEFAULT_LABEL
LEGACY_LABEL = "com.amaura.company-os"


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


def _legacy_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LEGACY_LABEL}.plist"


def _payload(repo_root: Path, *, poll_seconds: float) -> dict:
    try:
        return launch_agent_payload(repo_root, poll_seconds=poll_seconds)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def _require_success(result: subprocess.CompletedProcess[str], operation: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown launchctl failure").strip()
        raise RuntimeError(f"launchctl {operation} failed: {detail}")


def _restore_previous_service(
    *,
    domain: str,
    canonical: Path,
    previous_canonical: bytes | None,
    legacy: Path,
    legacy_existed: bool,
) -> None:
    _launchctl("bootout", domain, str(canonical))
    if previous_canonical is not None:
        _write_private(canonical, previous_canonical)
        restored = _launchctl("bootstrap", domain, str(canonical))
        if restored.returncode == 0:
            _launchctl("enable", f"{domain}/{LABEL}")
            _launchctl("kickstart", "-k", f"{domain}/{LABEL}")
        return
    canonical.unlink(missing_ok=True)
    if legacy_existed and legacy.exists():
        _launchctl("bootstrap", domain, str(legacy))


def install(repo_root: Path, *, poll_seconds: float, dry_run: bool) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("Amaura LaunchAgent installation is supported only on macOS")
    repo_root = repo_root.expanduser().resolve()
    plist, stdout, _stderr, _python = _paths(repo_root)
    legacy = _legacy_plist()
    payload = _payload(repo_root, poll_seconds=poll_seconds)
    rendered = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)
    if dry_run:
        sys.stdout.buffer.write(rendered)
        return 0

    previous_canonical = plist.read_bytes() if plist.exists() else None
    legacy_existed = legacy.exists()
    domain = f"gui/{os.getuid()}"
    stdout.parent.mkdir(parents=True, exist_ok=True)

    # Stop historical authority before starting the canonical daemon, but retain
    # its plist until canonical verification succeeds so rollback is possible.
    if legacy_existed:
        _launchctl("bootout", domain, str(legacy))
    _launchctl("bootout", domain, str(plist))
    _write_private(plist, rendered)

    try:
        _require_success(_launchctl("bootstrap", domain, str(plist)), "bootstrap")
        _require_success(_launchctl("enable", f"{domain}/{LABEL}"), "enable")
        _require_success(_launchctl("kickstart", "-k", f"{domain}/{LABEL}"), "kickstart")
        verify = _launchctl("print", f"{domain}/{LABEL}")
        _require_success(verify, "print")
        if LABEL not in (verify.stdout or "") and LABEL not in (verify.stderr or ""):
            raise RuntimeError("launchctl verification did not identify the canonical Amaura service")
    except Exception:
        _restore_previous_service(
            domain=domain,
            canonical=plist,
            previous_canonical=previous_canonical,
            legacy=legacy,
            legacy_existed=legacy_existed,
        )
        raise

    if legacy_existed:
        legacy.unlink(missing_ok=True)
    print(f"Installed and verified {LABEL}: {plist}")
    return 0


def uninstall(repo_root: Path, *, dry_run: bool) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("Amaura LaunchAgent installation is supported only on macOS")
    plist, _stdout, _stderr, _python = _paths(repo_root.expanduser().resolve())
    legacy = _legacy_plist()
    if dry_run:
        print(f"Would remove {plist} and obsolete {legacy}")
        return 0
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist))
    _launchctl("bootout", domain, str(legacy))
    plist.unlink(missing_ok=True)
    legacy.unlink(missing_ok=True)
    print(f"Removed {LABEL} and any obsolete {LEGACY_LABEL} service")
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
