#!/usr/bin/env python3
"""Controlled live recovery for ARCH roots proven on isolated copies.

Default mode is read-only planning. ``--apply`` is intentionally refused while
the canonical ARCH LaunchAgent or local API is running. Before any live mutation
the script requires an exact clean source checkout, a PASS batch qualification
for the same Git source tree, dependency-ready failed ``internal_work`` roots,
no active execution lease, and a healthy audit chain. It creates a private
read-only SQLite backup and audit-checkpoint backup *before* opening a writable
CompanyStore, then re-queues only those exact roots. Downstream blocked tasks are
never changed by this maintenance command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.qualified_recovery import (
    apply_qualified_recovery,
    build_recovery_plan,
    load_qualification,
    validate_qualification,
    work_state_snapshot,
)
from jarvis.amaura.runtime import load_amaura_env
from jarvis.amaura.store import CompanyStore

_ARCH_LABEL = "com.amaura.arch"
_PID_PATTERN = re.compile(r"(?m)^\s*pid\s*=\s*(\d+)\s*$")


def _run(command: list[str], *, cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)


def _git_value(repo_root: Path, expression: str) -> str:
    result = _run(["git", "rev-parse", expression], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _tracked_dirty(repo_root: Path) -> bool:
    result = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_root)
    return result.returncode != 0 or bool(result.stdout.strip())


def _arch_launchd_pid() -> int:
    if sys.platform != "darwin":
        return 0
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{_ARCH_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return 0
    match = _PID_PATTERN.search("\n".join((result.stdout, result.stderr)))
    return int(match.group(1)) if match else 0


def _api_port_accepting() -> bool:
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    try:
        port = int(os.environ.get("JARVIS_PORT", "8000"))
    except ValueError:
        return True
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _copy_private(source: Path, destination: Path) -> str:
    if not source.is_file():
        return ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if os.name == "posix":
        destination.chmod(0o600)
    return str(destination)


def _sqlite_read_only_backup(source: Path, destination: Path) -> Path:
    """Capture the exact live DB before any writable CompanyStore is opened."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=10.0)) as source_connection:
        with closing(sqlite3.connect(destination)) as backup_connection:
            source_connection.backup(backup_connection)
    if os.name == "posix":
        destination.chmod(0o600)
    return destination


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"Recovery Evidence: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-queue only ARCH roots proven by copied E2E qualification")
    parser.add_argument("--env-file", default=".env.amaura.v7live")
    parser.add_argument("--qualification-summary", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    parser.add_argument(
        "--reason",
        default="Deploy independently qualified evidence and reviewer repair",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the qualified retry; default is read-only plan")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    if _tracked_dirty(repo_root):
        raise SystemExit("Tracked checkout is dirty; refuse qualified live recovery")
    actual_sha = _git_value(repo_root, "HEAD")
    tree_sha = _git_value(repo_root, "HEAD^{tree}")
    if actual_sha != args.expected_sha:
        raise SystemExit(f"Exact-build mismatch: expected {args.expected_sha}, got {actual_sha}")
    if tree_sha == "unknown":
        raise SystemExit("Unable to resolve current Git source-tree SHA")

    env_file = Path(args.env_file).expanduser().resolve()
    load_amaura_env(env_file, override=True, require_private_permissions=True)
    data_dir = os.environ.get("AMAURA_DATA_DIR", "").strip()
    if not data_dir:
        raise SystemExit("AMAURA_DATA_DIR is not configured by the supplied environment file")
    live_db = Path(data_dir).expanduser().resolve() / "amaura.db"
    if not live_db.is_file():
        raise SystemExit(f"Live CompanyStore database not found: {live_db}")

    qualification_path = Path(args.qualification_summary).expanduser().resolve()
    try:
        qualification = load_qualification(qualification_path)
        qualified_results = validate_qualification(qualification, candidate_tree_sha=tree_sha)
        plan = build_recovery_plan(live_db, qualified_results)
    except GovernanceError as exc:
        raise SystemExit(f"FAIL CLOSED: {exc}") from exc

    plan_report = {
        "qualification": "ARCH_QUALIFIED_ROOT_RECOVERY_PLAN",
        "status": "READY" if plan else "FAIL",
        "apply_requested": bool(args.apply),
        "candidate_sha": actual_sha,
        "candidate_tree_sha": tree_sha,
        "qualification_summary": str(qualification_path),
        "live_db": str(live_db),
        "root_count": len(plan),
        "roots": [
            {
                "task_id": card["task_id"],
                "title": card["title"],
                "current_state": card["current_state"],
                "action_type": card["action_type"],
                "dependencies": card["dependencies"],
                "previous_evidence_count": len(card["previous_evidence"]),
            }
            for card in plan
        ],
        "downstream_tasks_will_be_manually_unblocked": False,
    }
    print(json.dumps(plan_report, indent=2, sort_keys=True))
    if not args.apply:
        return 0

    arch_pid = _arch_launchd_pid()
    if arch_pid > 0:
        raise SystemExit(
            f"FAIL CLOSED: {_ARCH_LABEL} is running with pid={arch_pid}. "
            "Stop the canonical ARCH service before controlled live root recovery."
        )
    if _api_port_accepting():
        raise SystemExit(
            "FAIL CLOSED: the configured ARCH API port is accepting connections. "
            "Stop any interactive/legacy ARCH or JARVIS process before live recovery."
        )

    before_states = work_state_snapshot(live_db)
    target_ids = {str(card["task_id"]) for card in plan}
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    evidence_dir = Path(args.evidence_dir).expanduser().resolve()
    recovery_dir = evidence_dir / f"{stamp}_ARCH_QUALIFIED_ROOT_RECOVERY"
    backup_dir = recovery_dir / "backup"
    report_path = recovery_dir / "summary.json"
    backup_db = backup_dir / "amaura.db"
    backup_checkpoint = ""

    # Back up the live SQLite snapshot and external checkpoint before any code
    # opens the source DB with write capability or runs schema migration hooks.
    _sqlite_read_only_backup(live_db, backup_db)
    checkpoint_value = os.environ.get("AMAURA_AUDIT_CHECKPOINT_PATH", "").strip()
    if checkpoint_value:
        checkpoint = Path(checkpoint_value).expanduser().resolve()
        if checkpoint.is_file():
            backup_checkpoint = _copy_private(checkpoint, backup_dir / "audit-head.json")

    store = CompanyStore(live_db)
    try:
        integrity_before = store.integrity_check()
        if not integrity_before.get("ok"):
            raise GovernanceError("Live CompanyStore failed integrity before qualified recovery")
        actor = os.environ.get("AMAURA_FOUNDER_ID", "founder").strip() or "founder"
        result = apply_qualified_recovery(
            store,
            plan,
            qualification_path=str(qualification_path),
            candidate_tree_sha=tree_sha,
            reason=args.reason,
            actor=actor,
        )
    except GovernanceError as exc:
        raise SystemExit(f"FAIL CLOSED: {exc}; backup={backup_db}") from exc
    finally:
        store.close()

    after_states = work_state_snapshot(live_db)
    changed_non_targets = {
        item_id: {"before": state, "after": after_states.get(item_id, "missing")}
        for item_id, state in before_states.items()
        if item_id not in target_ids and after_states.get(item_id) != state
    }
    if changed_non_targets:
        raise SystemExit(
            "FAIL CLOSED: non-target work-item state changed during recovery; "
            f"possible concurrent writer detected; backup={backup_db}"
        )
    wrong_target_states = {
        item_id: after_states.get(item_id, "missing")
        for item_id in target_ids
        if after_states.get(item_id) != "assigned"
    }
    if wrong_target_states:
        raise SystemExit(f"FAIL CLOSED: recovered roots are not all assigned: {wrong_target_states}; backup={backup_db}")

    report = {
        "qualification": "ARCH_QUALIFIED_ROOT_RECOVERY",
        "status": "PASS",
        "candidate_sha": actual_sha,
        "candidate_tree_sha": tree_sha,
        "qualification_summary": str(qualification_path),
        "source_backup": str(backup_db),
        "backup_created_before_writable_open": True,
        "audit_checkpoint_backup": backup_checkpoint,
        "live_db": str(live_db),
        "recovered_root_count": len(target_ids),
        "recovered_root_ids": sorted(target_ids),
        "non_target_state_changes": changed_non_targets,
        "downstream_tasks_manually_unblocked": False,
        "result": result,
    }
    _write_report(report_path, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
