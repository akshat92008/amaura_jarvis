#!/usr/bin/env python3
"""Install or remove the one canonical ARCH LaunchAgent on macOS.

Successful installation proves the new ARCH process is running before deleting
legacy company-runtime plists. A failed install rolls back to the previous
service state rather than weakening availability or authority boundaries.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.amaura.runtime import load_amaura_env
from jarvis.arch_macos_service import DEFAULT_LABEL, LEGACY_LABELS, launch_agent_payload

_PID_PATTERN = re.compile(r"(?m)^\s*pid\s*=\s*(\d+)\s*$")
_SERVICE_START_TIMEOUT_SECONDS = 45.0
_SERVICE_POLL_INTERVAL_SECONDS = 0.25


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the canonical ARCH LaunchAgent")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False, timeout=30)


def _canonical_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{DEFAULT_LABEL}.plist"


def _legacy_plists() -> dict[str, Path]:
    base = Path.home() / "Library" / "LaunchAgents"
    return {label: base / f"{label}.plist" for label in LEGACY_LABELS}


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


def _health_url() -> str:
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    try:
        port = int(os.environ.get("JARVIS_PORT", "8000"))
    except ValueError as exc:
        raise RuntimeError("JARVIS_PORT must be an integer for ARCH service verification") from exc
    return f"http://{host}:{port}/api/health"


def _health_ok() -> bool:
    request = urllib.request.Request(_health_url(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return int(response.status) == 200
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _wait_for_service(*, domain: str, timeout: float = _SERVICE_START_TIMEOUT_SECONDS) -> int:
    """Wait for launchd to own one live, healthy ARCH process after bootstrap.

    The canonical plist is RunAtLoad, so ``launchctl bootstrap`` is the start
    operation. Do not follow it with ``kickstart -k``: that can kill the fresh
    process while it is still initializing and was observed to hang on the
    target Mac. Verification is instead read-only polling of launchd + health.
    """
    deadline = time.monotonic() + max(0.1, timeout)
    last_detail = "service not yet visible"
    while time.monotonic() < deadline:
        verify = _launchctl("print", f"{domain}/{DEFAULT_LABEL}")
        if verify.returncode == 0:
            output = "\n".join(part for part in (verify.stdout, verify.stderr) if part)
            match = _PID_PATTERN.search(output)
            if match is not None and int(match.group(1)) > 1:
                pid = int(match.group(1))
                if _health_ok():
                    return pid
                last_detail = f"launchd reports pid={pid}, but {_health_url()} is not healthy yet"
            else:
                last_detail = "launchd service is visible but has no live PID yet"
        else:
            last_detail = (verify.stderr or verify.stdout or "launchd service not visible yet").strip()
        time.sleep(_SERVICE_POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"ARCH service did not become healthy within {timeout:.0f}s: {last_detail}")


def _verify_installed_service(*, domain: str, canonical: Path, expected_payload: dict) -> int:
    try:
        installed_payload = plistlib.loads(canonical.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeError(f"ARCH LaunchAgent plist could not be verified: {exc}") from exc
    if installed_payload != expected_payload:
        raise RuntimeError("Installed LaunchAgent payload does not match the canonical ARCH contract")

    pid = _wait_for_service(domain=domain)

    for label in LEGACY_LABELS:
        if _launchctl("print", f"{domain}/{label}").returncode == 0:
            raise RuntimeError(f"Legacy split runtime {label} is still loaded")
    return pid


def _restore_previous_services(
    *,
    domain: str,
    canonical: Path,
    previous_canonical: bytes | None,
    legacy: dict[str, Path],
    legacy_existed: dict[str, bool],
) -> None:
    _launchctl("bootout", domain, str(canonical))
    if previous_canonical is not None:
        _write_private(canonical, previous_canonical)
        if _launchctl("bootstrap", domain, str(canonical)).returncode == 0:
            _launchctl("enable", f"{domain}/{DEFAULT_LABEL}")
    else:
        canonical.unlink(missing_ok=True)
    for label, path in legacy.items():
        if legacy_existed[label] and path.exists():
            _launchctl("bootstrap", domain, str(path))


def install(repo_root: Path, *, dry_run: bool) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("ARCH LaunchAgent installation is supported only on macOS")
    repo_root = repo_root.expanduser().resolve()
    canonical = _canonical_plist()
    legacy = _legacy_plists()
    payload = launch_agent_payload(repo_root)
    rendered = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)
    if dry_run:
        sys.stdout.buffer.write(rendered)
        return 0

    # Verification must target the same host/port ARCH will load from its
    # private environment. Secrets remain process-local and never enter plist.
    load_amaura_env(repo_root / ".env.amaura", override=True, require_private_permissions=True)

    previous_canonical = canonical.read_bytes() if canonical.exists() else None
    legacy_existed = {label: path.exists() for label, path in legacy.items()}
    domain = f"gui/{os.getuid()}"
    (Path.home() / ".jarvis" / "logs").mkdir(parents=True, exist_ok=True)

    for path in legacy.values():
        _launchctl("bootout", domain, str(path))
    _launchctl("bootout", domain, str(canonical))
    _write_private(canonical, rendered)

    try:
        _require_success(_launchctl("bootstrap", domain, str(canonical)), "bootstrap")
        _require_success(_launchctl("enable", f"{domain}/{DEFAULT_LABEL}"), "enable")
        pid = _verify_installed_service(domain=domain, canonical=canonical, expected_payload=payload)
    except Exception:
        _restore_previous_services(
            domain=domain,
            canonical=canonical,
            previous_canonical=previous_canonical,
            legacy=legacy,
            legacy_existed=legacy_existed,
        )
        raise

    for path in legacy.values():
        path.unlink(missing_ok=True)
    print(f"Installed and verified {DEFAULT_LABEL} pid={pid}: {canonical}")
    return 0


def uninstall(repo_root: Path, *, dry_run: bool) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("ARCH LaunchAgent installation is supported only on macOS")
    _ = repo_root.expanduser().resolve()
    canonical = _canonical_plist()
    legacy = _legacy_plists()
    if dry_run:
        print(f"Would remove {canonical} and legacy split-runtime LaunchAgents")
        return 0
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(canonical))
    canonical.unlink(missing_ok=True)
    for path in legacy.values():
        _launchctl("bootout", domain, str(path))
        path.unlink(missing_ok=True)
    print(f"Removed {DEFAULT_LABEL} and legacy split-runtime LaunchAgents")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if shutil.which("launchctl") is None and not args.dry_run:
        raise RuntimeError("launchctl is not available")
    repo_root = Path(args.repo_root)
    if args.install:
        return install(repo_root, dry_run=args.dry_run)
    return uninstall(repo_root, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
