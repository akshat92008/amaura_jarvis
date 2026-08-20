"""Fail-closed recovery of live internal root tasks after copied qualification.

This module does not decide that a repair is safe. It consumes the signed-off
qualification summary produced by ``qualify_arch_company_roots.py`` and will
only re-queue the exact failed internal roots that were independently proven to
complete on isolated copies of the same source tree. Downstream tasks are never
manually unblocked.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.store import CompanyStore


def _decode_json(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def load_qualification(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise GovernanceError(f"Qualified-recovery summary is unreadable: {source}") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("Qualified-recovery summary must contain one JSON object")
    return payload


def validate_qualification(report: dict[str, Any], *, candidate_tree_sha: str) -> list[dict[str, Any]]:
    """Return exactly the qualified root results or fail closed."""
    if report.get("qualification") != "ARCH_COMPANY_ROOT_E2E":
        raise GovernanceError("Recovery requires an ARCH_COMPANY_ROOT_E2E qualification summary")
    if report.get("status") != "PASS":
        raise GovernanceError("Company-root qualification did not PASS")
    if report.get("source_writable_connection_opened") is not False:
        raise GovernanceError("Qualification does not prove that the source CompanyStore stayed read-only")
    qualified_tree = str(report.get("candidate_tree_sha") or "").strip()
    if not qualified_tree:
        raise GovernanceError("Qualification is missing candidate_tree_sha")
    if qualified_tree != candidate_tree_sha:
        raise GovernanceError(
            f"Qualified source tree does not match this checkout: qualified={qualified_tree} current={candidate_tree_sha}"
        )
    unsafe = list(report.get("unsafe_or_manual_roots") or [])
    if unsafe:
        raise GovernanceError("Qualification contains unsafe or manually handled roots; automatic live recovery is forbidden")
    results = list(report.get("results") or [])
    root_count = int(report.get("root_blocker_count") or 0)
    passed_count = int(report.get("passed_root_count") or 0)
    if root_count <= 0 or len(results) != root_count or passed_count != root_count:
        raise GovernanceError("Qualification does not cover every reported root blocker")

    seen: set[str] = set()
    qualified: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            raise GovernanceError("Qualification contains a malformed root result")
        task_id = str(item.get("task_id") or "").strip()
        if not task_id or task_id in seen:
            raise GovernanceError("Qualification contains a missing or duplicate root task id")
        seen.add(task_id)
        if item.get("status") != "PASS" or int(item.get("returncode", 1)) != 0:
            raise GovernanceError(f"Root {task_id} did not PASS isolated qualification")
        if item.get("final_state") != TaskState.COMPLETED.value:
            raise GovernanceError(f"Root {task_id} was not completed in isolated qualification")
        if item.get("reviewer_distinct_from_worker") is not True:
            raise GovernanceError(f"Root {task_id} lacks independent reviewer-model proof")
        if item.get("criteria_all_passed") is not True:
            raise GovernanceError(f"Root {task_id} lacks complete acceptance-criterion proof")
        qualified.append(dict(item))
    return qualified


def _read_live_rows(db_path: Path) -> dict[str, dict[str, Any]]:
    uri = f"file:{db_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id,item_type,title,state,action_type,dependencies,evidence,summary,metadata FROM work_items"
        ).fetchall()
        return {
            str(row["id"]): {
                **dict(row),
                "dependencies": _decode_json(row["dependencies"], []),
                "evidence": _decode_json(row["evidence"], []),
                "metadata": _decode_json(row["metadata"], {}),
            }
            for row in rows
        }
    finally:
        connection.close()


def _active_execution_ids(db_path: Path, task_ids: list[str]) -> set[str]:
    if not task_ids:
        return set()
    uri = f"file:{db_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        placeholders = ",".join("?" for _ in task_ids)
        rows = connection.execute(
            f"SELECT DISTINCT task_id FROM execution_runs WHERE task_id IN ({placeholders}) "  # noqa: S608 - placeholders only
            "AND state IN ('leased','running')",
            tuple(task_ids),
        ).fetchall()
        return {str(row[0]) for row in rows}
    finally:
        connection.close()


def build_recovery_plan(
    db_path: str | Path,
    qualified_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inspect live state read-only and return exact roots eligible for retry."""
    database = Path(db_path).expanduser().resolve()
    if not database.is_file():
        raise GovernanceError(f"Live CompanyStore database does not exist: {database}")
    rows = _read_live_rows(database)
    task_ids = [str(item.get("task_id") or "") for item in qualified_results]
    active = _active_execution_ids(database, task_ids)
    plan: list[dict[str, Any]] = []
    for result in qualified_results:
        task_id = str(result["task_id"])
        task = rows.get(task_id)
        if task is None:
            raise GovernanceError(f"Qualified root is missing from live CompanyStore: {task_id}")
        if task.get("item_type") != "task":
            raise GovernanceError(f"Qualified root is not a task in live CompanyStore: {task_id}")
        if task.get("state") != TaskState.FAILED.value:
            raise GovernanceError(f"Qualified root {task_id} is no longer failed; current state={task.get('state')!r}")
        if task.get("action_type") != "internal_work":
            raise GovernanceError(f"Qualified root {task_id} is consequential; automatic retry is forbidden")
        if task_id in active:
            raise GovernanceError(f"Qualified root {task_id} still has an active execution lease")
        unresolved = [
            dep
            for dep in list(task.get("dependencies") or [])
            if dep not in rows or rows[dep].get("state") != TaskState.COMPLETED.value
        ]
        if unresolved:
            raise GovernanceError(f"Qualified root {task_id} is not dependency-ready: {unresolved!r}")
        plan.append(
            {
                "task_id": task_id,
                "title": str(task.get("title") or result.get("title") or ""),
                "current_state": str(task.get("state") or ""),
                "action_type": str(task.get("action_type") or ""),
                "dependencies": list(task.get("dependencies") or []),
                "previous_summary": str(task.get("summary") or ""),
                "previous_evidence": list(task.get("evidence") or []),
                "qualification_evidence": str(result.get("evidence") or ""),
            }
        )
    return plan


def work_state_snapshot(db_path: str | Path) -> dict[str, str]:
    rows = _read_live_rows(Path(db_path).expanduser().resolve())
    return {task_id: str(row.get("state") or "") for task_id, row in rows.items()}


def _compact_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                key: item.get(key)
                for key in ("type", "reference", "sha256", "success")
                if item.get(key) not in (None, "")
            }
        )
    return compact


def apply_qualified_recovery(
    store: CompanyStore,
    plan: list[dict[str, Any]],
    *,
    qualification_path: str,
    candidate_tree_sha: str,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    """Re-queue only proven internal roots; never touch downstream blocked tasks."""
    clean_reason = " ".join(reason.split()).strip()
    if not clean_reason:
        raise GovernanceError("Qualified live recovery requires a non-empty reason")
    if not plan:
        raise GovernanceError("Qualified live recovery plan is empty")
    before_integrity = store.integrity_check()
    if not before_integrity.get("ok"):
        raise GovernanceError("Live CompanyStore failed integrity before qualified recovery")

    recovered: list[dict[str, Any]] = []
    for card in plan:
        task_id = str(card["task_id"])
        task = store.get_work_item(task_id)
        if task.get("state") != TaskState.FAILED.value or task.get("action_type") != "internal_work":
            raise GovernanceError(f"Live root changed before recovery could be applied: {task_id}")
        unresolved = [
            dep
            for dep in list(task.get("dependencies") or [])
            if store.get_work_item(dep).get("state") != TaskState.COMPLETED.value
        ]
        if unresolved:
            raise GovernanceError(f"Live root {task_id} gained unresolved dependencies: {unresolved!r}")

        metadata = dict(task.get("metadata") or {})
        history = list(metadata.get("qualified_repair_retries") or [])
        recovery_entry = {
            "at": datetime.now(UTC).isoformat(),
            "reason": clean_reason,
            "qualification_path": qualification_path,
            "candidate_tree_sha": candidate_tree_sha,
            "previous_state": str(task.get("state") or ""),
            "previous_summary": str(task.get("summary") or "")[-6000:],
            "previous_evidence": _compact_evidence(list(task.get("evidence") or [])),
        }
        history.append(recovery_entry)
        metadata["qualified_repair_retries"] = history[-10:]
        metadata["qualified_repair_tree_sha"] = candidate_tree_sha
        metadata["qualified_repair_reason"] = clean_reason
        metadata["qualified_repair_qualification"] = qualification_path
        retry_summary = (
            f"QUALIFIED REPAIR RETRY: {clean_reason}\n\n"
            f"Previous failure:\n{str(task.get('summary') or '').strip()}"
        ).strip()

        # The previous evidence references are preserved in metadata for audit,
        # but the active evidence field is cleared. A fresh review therefore
        # cannot certify the retried task using stale evidence from the failed
        # execution.
        with store.atomic_block():
            updated = store.update_work_item(
                task_id,
                state=TaskState.ASSIGNED.value,
                summary=retry_summary,
                evidence=[],
                metadata=metadata,
            )
            store.publish_event(
                "task.qualified_retry",
                task_id,
                {
                    "actor": actor,
                    "reason": clean_reason,
                    "candidate_tree_sha": candidate_tree_sha,
                    "qualification_path": qualification_path,
                },
            )
        store.audit(
            actor,
            "qualified_retry",
            "task",
            task_id,
            "allowed",
            {
                "reason": clean_reason,
                "candidate_tree_sha": candidate_tree_sha,
                "qualification_path": qualification_path,
                "previous_state": TaskState.FAILED.value,
                "new_state": TaskState.ASSIGNED.value,
                "previous_evidence_count": len(task.get("evidence") or []),
            },
        )
        recovered.append(
            {
                "task_id": task_id,
                "title": str(updated.get("title") or ""),
                "state": str(updated.get("state") or ""),
            }
        )

    after_integrity = store.integrity_check()
    if not after_integrity.get("ok"):
        raise GovernanceError("Live CompanyStore failed integrity after qualified recovery")
    return {
        "status": "PASS",
        "recovered": recovered,
        "integrity_before": before_integrity,
        "integrity_after": after_integrity,
    }


__all__ = [
    "apply_qualified_recovery",
    "build_recovery_plan",
    "load_qualification",
    "validate_qualification",
    "work_state_snapshot",
]
