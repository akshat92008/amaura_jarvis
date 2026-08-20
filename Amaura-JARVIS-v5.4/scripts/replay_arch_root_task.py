#!/usr/bin/env python3
"""Safely replay one failed internal ARCH root task against an isolated DB copy.

This qualification harness never opens the source CompanyStore for writing. It
copies the external audit checkpoint first, then uses SQLite's read-only backup
API so the copied checkpoint can only lag (never lead) the copied audit log.
All replay evidence, audit updates, task state changes, and internal assets are
written under a qualification directory. No supervisor/outbox loop is started.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.models import TaskState
from jarvis.amaura.runtime import load_amaura_env

SAFE_ACTION_TYPES = {"internal_work"}
TERMINAL_PROOF_STATES = {
    TaskState.AWAITING_REVIEW.value,
    TaskState.AWAITING_APPROVAL.value,
    TaskState.COMPLETED.value,
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False, timeout=10)


def _git_sha() -> str:
    result = _run("git", "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _tracked_dirty() -> bool:
    result = _run("git", "status", "--porcelain", "--untracked-files=no")
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def _read_task(db_path: Path, task_id: str) -> dict[str, Any]:
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM work_items WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        task = dict(row)
        for key in ("acceptance_criteria", "dependencies", "evidence", "metadata"):
            default = "{}" if key == "metadata" else "[]"
            try:
                task[key] = json.loads(str(task.get(key) or default))
            except (TypeError, ValueError, json.JSONDecodeError):
                task[key] = {} if key == "metadata" else []
        return task
    finally:
        connection.close()


def _unresolved_dependencies(db_path: Path, task: dict[str, Any]) -> list[str]:
    dependencies = [str(item) for item in task.get("dependencies") or [] if str(item)]
    if not dependencies:
        return []
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        unresolved: list[str] = []
        for dependency_id in dependencies:
            row = connection.execute("SELECT state FROM work_items WHERE id=?", (dependency_id,)).fetchone()
            if row is None or str(row[0]) != TaskState.COMPLETED.value:
                unresolved.append(dependency_id)
        return unresolved
    finally:
        connection.close()


def _sqlite_backup_read_only(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True, timeout=30.0)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    if os.name == "posix":
        destination.chmod(0o600)


def _prepare_copy(
    source_db: Path,
    source_checkpoint: Path | None,
    qualification_dir: Path,
) -> tuple[Path, Path | None]:
    data_dir = qualification_dir / "data"
    copied_db = data_dir / "amaura.db"
    copied_checkpoint: Path | None = None

    # Copy the checkpoint before the DB snapshot. The live checkpoint is allowed
    # to lag the DB, while the inverse is treated as rollback evidence.
    if source_checkpoint is not None:
        copied_checkpoint = qualification_dir / "trust" / "audit-head.json"
        copied_checkpoint.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_checkpoint, copied_checkpoint)
        if os.name == "posix":
            copied_checkpoint.chmod(0o600)

    _sqlite_backup_read_only(source_db, copied_db)
    return copied_db, copied_checkpoint


def _arm_isolated_copy(copied_db: Path, task_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(copied_db, timeout=10.0)
    try:
        row = connection.execute(
            "SELECT state,action_type FROM work_items WHERE id=? AND item_type='task'",
            (task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown copied task: {task_id}")
        if str(row[0]) != TaskState.FAILED.value:
            raise RuntimeError(f"Qualification target must be failed, got state={row[0]!r}")
        if str(row[1]) not in SAFE_ACTION_TYPES:
            raise RuntimeError(
                f"Qualification refuses consequential action_type={row[1]!r}; "
                f"allowed={sorted(SAFE_ACTION_TYPES)!r}"
            )

        # This is a qualification-only state transition on the copied DB. The
        # previous failure summary is intentionally preserved as retry context.
        connection.execute(
            "UPDATE work_items SET state=?,updated_at=? WHERE id=?",
            (TaskState.ASSIGNED.value, now, task_id),
        )
        connection.execute(
            """INSERT INTO system_controls(key,value,updated_by,updated_at)
            VALUES('external_actions_kill_switch','on','arch-qualification',?)
            ON CONFLICT(key) DO UPDATE SET
                value='on',updated_by='arch-qualification',updated_at=excluded.updated_at""",
            (now,),
        )
        connection.commit()
    finally:
        connection.close()


def _configure_replay_environment(qualification_dir: Path, copied_checkpoint: Path | None) -> None:
    os.environ["AMAURA_DATA_DIR"] = str((qualification_dir / "data").resolve())
    os.environ["AMAURA_EVIDENCE_DIR"] = str((qualification_dir / "evidence").resolve())
    os.environ["AMAURA_HANDOFF_DIR"] = str((qualification_dir / "handoffs").resolve())
    os.environ["AMAURA_BACKUP_DIR"] = str((qualification_dir / "backups").resolve())
    os.environ["JARVIS_DATA_DIR"] = str((qualification_dir / "jarvis-data").resolve())
    os.environ["JARVIS_LEGACY_TOOL_MODE"] = "disabled"
    os.environ["JARVIS_ENABLE_LEGACY_DIRECT_TOOLS"] = "0"
    os.environ["AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS"] = "0"
    if copied_checkpoint is not None:
        os.environ["AMAURA_AUDIT_CHECKPOINT_PATH"] = str(copied_checkpoint.resolve())
    else:
        os.environ.pop("AMAURA_AUDIT_CHECKPOINT_PATH", None)


def _report_path(qualification_dir: Path) -> Path:
    return qualification_dir / "summary.json"


def _write_report(qualification_dir: Path, report: dict[str, Any]) -> None:
    path = _report_path(qualification_dir)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"Evidence: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay one failed internal ARCH root task on an isolated DB copy")
    parser.add_argument("--env-file", default=".env.amaura.v7live")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    parser.add_argument("--max-iterations", type=int, default=12)
    args = parser.parse_args(argv)

    load_amaura_env(args.env_file, override=True, require_private_permissions=True)
    source_data_dir = os.environ.get("AMAURA_DATA_DIR", "").strip()
    if not source_data_dir:
        raise SystemExit("AMAURA_DATA_DIR is not configured by the supplied environment file")
    source_db = Path(source_data_dir).expanduser().resolve() / "amaura.db"
    if not source_db.is_file():
        raise SystemExit(f"Live CompanyStore database not found: {source_db}")

    actual_sha = _git_sha()
    if _tracked_dirty():
        raise SystemExit("Tracked checkout is dirty; refuse exact-build replay")
    if args.expected_sha and actual_sha != args.expected_sha:
        raise SystemExit(f"Exact-build mismatch: expected {args.expected_sha}, got {actual_sha}")

    source_task = _read_task(source_db, args.task_id)
    unresolved = _unresolved_dependencies(source_db, source_task)
    if source_task.get("item_type") != "task":
        raise SystemExit("Replay target is not a task")
    if str(source_task.get("state") or "") != TaskState.FAILED.value:
        raise SystemExit(f"Replay target must currently be failed, got {source_task.get('state')!r}")
    if str(source_task.get("action_type") or "") not in SAFE_ACTION_TYPES:
        raise SystemExit(
            f"Replay target action_type={source_task.get('action_type')!r} is not an allowed internal qualification action"
        )
    if unresolved:
        raise SystemExit(f"Replay target is not a root blocker; unresolved dependencies: {unresolved!r}")
    if not source_task.get("acceptance_criteria"):
        raise SystemExit("Replay target has no acceptance criteria; evidence-guard qualification is not applicable")

    checkpoint_value = os.environ.get("AMAURA_AUDIT_CHECKPOINT_PATH", "").strip()
    source_checkpoint = Path(checkpoint_value).expanduser().resolve() if checkpoint_value else None
    require_checkpoint = os.environ.get("AMAURA_REQUIRE_EXTERNAL_AUDIT_CHECKPOINT", "0") == "1"
    if source_checkpoint is not None and not source_checkpoint.is_file():
        raise SystemExit(f"Configured external audit checkpoint does not exist: {source_checkpoint}")
    if require_checkpoint and source_checkpoint is None:
        raise SystemExit("Strict runtime requires an external audit checkpoint, but none is configured")

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    qualification_dir = (
        Path(args.evidence_dir).expanduser().resolve() / f"{stamp}_ARCH_ROOT_REPLAY_{args.task_id}"
    )
    qualification_dir.mkdir(parents=True, exist_ok=False)

    base_report: dict[str, Any] = {
        "qualification": "ARCH_ROOT_TASK_REPLAY",
        "source_mode": "sqlite_read_only_backup",
        "source_db": str(source_db),
        "task_id": args.task_id,
        "task_title": str(source_task.get("title") or ""),
        "task_owner": str(source_task.get("owner_id") or ""),
        "action_type": str(source_task.get("action_type") or ""),
        "acceptance_criteria_count": len(source_task.get("acceptance_criteria") or []),
        "unresolved_dependencies": unresolved,
        "git_sha": actual_sha,
        "source_state": str(source_task.get("state") or ""),
        "source_writable_connection_opened": False,
        "external_actions_kill_switch": "on_in_copy",
    }

    control: AmauraControlPlane | None = None
    try:
        copied_db, copied_checkpoint = _prepare_copy(source_db, source_checkpoint, qualification_dir)
        _arm_isolated_copy(copied_db, args.task_id)
        _configure_replay_environment(qualification_dir, copied_checkpoint)

        control = AmauraControlPlane(db_path=copied_db, audit_checkpoint_path=copied_checkpoint)
        # Append a qualification-only audit record to the copy. Besides making
        # the state reset explicit, this advances a legitimately lagging copied
        # checkpoint to the copied DB's current audit head before integrity proof.
        control.store.audit(
            "arch-qualification",
            "prepare_root_replay",
            "task",
            args.task_id,
            "allowed",
            {"source_mode": "sqlite_read_only_backup", "external_actions_kill_switch": "on"},
        )
        integrity_before = control.store.integrity_check()
        if not integrity_before.get("ok"):
            raise RuntimeError(f"Copied CompanyStore failed integrity check before replay: {integrity_before}")

        result = GovernedTaskRunner(control).run(args.task_id, max_iterations=args.max_iterations)
        final_task = control.store.get_work_item(args.task_id)
        evidence = list(final_task.get("evidence") or [])
        successful_tool_results = [
            item for item in evidence if item.get("type") == "tool_result" and bool(item.get("success"))
        ]
        integrity_after = control.store.integrity_check()
        final_state = str(final_task.get("state") or "")
        passed = bool(successful_tool_results) and final_state in TERMINAL_PROOF_STATES and bool(integrity_after.get("ok"))

        report = {
            **base_report,
            "status": "PASS" if passed else "FAIL",
            "copied_db": str(copied_db),
            "final_state": final_state,
            "runner_status": str(result.get("status") or ""),
            "iterations": int(result.get("iterations") or 0),
            "evidence_count": len(evidence),
            "evidence_types": [str(item.get("type") or "") for item in evidence],
            "successful_tool_evidence_count": len(successful_tool_results),
            "successful_tools": [str(item.get("tool") or "") for item in successful_tool_results],
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
        }
        _write_report(qualification_dir, report)
        return 0 if passed else 1
    except Exception as exc:  # noqa: BLE001 - qualification must preserve a failure report
        report = {
            **base_report,
            "status": "FAIL",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc)[:2000],
        }
        _write_report(qualification_dir, report)
        return 1
    finally:
        if control is not None:
            control.close()


if __name__ == "__main__":
    raise SystemExit(main())
