"""Fail-closed local runtime certification for Amaura JARVIS.

This combines repository provenance, the live production doctor, and the
founder-facing real PTY qualification into one machine-readable verdict.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _load_pty_qualifier(root: Path) -> Any:
    path = root / "scripts" / "qualify_real_cli_pty.py"
    if not path.is_file():
        raise RuntimeError(f"Missing PTY qualification harness: {path}")
    spec = importlib.util.spec_from_file_location("amaura_local_pty_qualifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PTY qualification harness: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    qualifier = getattr(module, "run_full_pty_qualification", None)
    if not callable(qualifier):
        raise RuntimeError("PTY qualification harness does not expose run_full_pty_qualification()")
    return qualifier


def certify_local_runtime(repository_root: str | Path) -> dict[str, Any]:
    """Return a fail-closed daily-use verdict for the exact local checkout."""

    root = Path(repository_root).expanduser().resolve()
    if not (root / ".git").exists():
        return {
            "ready": False,
            "error": "source_checkout_required",
            "repository_root": str(root),
        }

    provenance: dict[str, Any] = {
        "head": "",
        "origin_main": "",
        "head_matches_origin_main": False,
        "worktree_clean": False,
        "fetch_ok": False,
    }
    try:
        _git(root, "fetch", "--quiet", "origin", "main")
        provenance["fetch_ok"] = True
        provenance["head"] = _git(root, "rev-parse", "HEAD")
        provenance["origin_main"] = _git(root, "rev-parse", "origin/main")
        provenance["head_matches_origin_main"] = provenance["head"] == provenance["origin_main"]
        provenance["worktree_clean"] = not bool(_git(root, "status", "--porcelain"))
    except Exception as exc:
        provenance["error"] = f"{type(exc).__name__}: {exc}"

    from jarvis.amaura.doctor import certify_release

    try:
        doctor = certify_release(repository_root=root, static_only=False)
    except Exception as exc:
        doctor = {
            "ready": False,
            "source_certified": False,
            "production_ready": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    try:
        pty_report = _load_pty_qualifier(root)()
    except Exception as exc:
        pty_report = {
            "overall": "FAIL",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    ready = bool(
        provenance.get("fetch_ok")
        and provenance.get("head_matches_origin_main")
        and provenance.get("worktree_clean")
        and doctor.get("production_ready") is True
        and doctor.get("ready") is True
        and pty_report.get("overall") == "PASS"
        and pty_report.get("single_mission_continuity") == "PASS"
        and pty_report.get("result_consistency") == "PASS"
        and pty_report.get("multi_mission_continuity") == "PASS"
        and pty_report.get("restart_test") == "PASS"
    )

    return {
        "ready": ready,
        "verdict": "READY_FOR_DAILY_USE" if ready else "NOT_READY_FOR_DAILY_USE",
        "repository_root": str(root),
        "provenance": provenance,
        "production_gate": doctor,
        "real_pty": pty_report,
    }
