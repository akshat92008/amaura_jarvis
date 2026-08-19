#!/usr/bin/env python3
"""Read-only root-cause audit for a blocked ARCH company runtime.

The live CompanyStore is opened through SQLite URI mode=ro, so this diagnostic
cannot mutate tasks, approvals, alerts, events, or audit history. It reduces a
large blocked queue into upstream root blockers and their downstream impact.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jarvis.amaura.runtime import load_amaura_env

PROBLEM_STATES = {"failed", "blocked"}
COMPLETE_STATE = "completed"
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_ -]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False, timeout=10)


def git_sha() -> str:
    result = _run("git", "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def tracked_dirty() -> bool:
    result = _run("git", "status", "--porcelain", "--untracked-files=no")
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _redact(text: str, limit: int = 260) -> str:
    clean = " ".join(str(text or "").split())
    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub("[REDACTED]", clean)
    return clean[:limit]


def _dependency_ids(task: dict[str, Any]) -> list[str]:
    raw = _loads(task.get("dependencies"), [])
    result: list[str] = []
    if not isinstance(raw, list):
        return result
    for item in raw:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            candidate = item.get("id") or item.get("task_id") or item.get("dependency_id")
            if candidate:
                result.append(str(candidate))
    return result


def _task_card(task: dict[str, Any], *, unresolved: list[str], impact: int = 0) -> dict[str, Any]:
    return {
        "id": str(task.get("id") or ""),
        "title": str(task.get("title") or ""),
        "workflow_id": str(task.get("workflow_id") or ""),
        "owner_id": str(task.get("owner_id") or ""),
        "state": str(task.get("state") or ""),
        "priority": int(task.get("priority") or 0),
        "updated_at": str(task.get("updated_at") or ""),
        "unresolved_dependencies": unresolved,
        "blocked_descendants": impact,
        "summary_excerpt": _redact(str(task.get("summary") or "")),
    }


def analyze(tasks: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    live = [task for task in tasks if not (_loads(task.get("metadata"), {}) or {}).get("superseded_by")]
    by_id = {str(task.get("id") or ""): task for task in live if task.get("id")}

    unresolved: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = defaultdict(list)
    for task_id, task in by_id.items():
        deps = [dep for dep in _dependency_ids(task) if dep in by_id]
        unresolved[task_id] = [dep for dep in deps if str(by_id[dep].get("state") or "") != COMPLETE_STATE]
        for dep in deps:
            reverse[dep].append(task_id)

    def blocked_descendants(root_id: str) -> set[str]:
        blocked_found: set[str] = set()
        visited = {root_id}
        stack = [root_id]
        while stack:
            parent = stack.pop()
            for child_id in reverse.get(parent, []):
                if child_id in visited:
                    continue
                visited.add(child_id)
                child = by_id.get(child_id) or {}
                child_state = str(child.get("state") or "")
                if child_state not in PROBLEM_STATES:
                    continue
                if child_state == "blocked":
                    blocked_found.add(child_id)
                # Failed descendants may themselves block a deeper chain, so
                # keep traversing through both failed and blocked problem nodes.
                stack.append(child_id)
        return blocked_found

    failed = [task for task in live if str(task.get("state") or "") == "failed"]
    blocked = [task for task in live if str(task.get("state") or "") == "blocked"]
    running = [task for task in live if str(task.get("state") or "") == "in_progress"]

    root_tasks: list[dict[str, Any]] = []
    for task in failed:
        task_id = str(task.get("id") or "")
        upstream_problem = [
            dep for dep in unresolved.get(task_id, []) if str((by_id.get(dep) or {}).get("state") or "") in PROBLEM_STATES
        ]
        if not upstream_problem:
            root_tasks.append(task)

    blocked_without_unresolved = [
        task for task in blocked if not unresolved.get(str(task.get("id") or ""), [])
    ]
    root_ids = {str(task.get("id") or "") for task in root_tasks}
    for task in blocked_without_unresolved:
        task_id = str(task.get("id") or "")
        if task_id not in root_ids:
            root_tasks.append(task)
            root_ids.add(task_id)

    root_cards: list[dict[str, Any]] = []
    for task in root_tasks:
        task_id = str(task.get("id") or "")
        impact = len(blocked_descendants(task_id))
        root_cards.append(_task_card(task, unresolved=unresolved.get(task_id, []), impact=impact))
    root_cards.sort(key=lambda item: (-int(item["blocked_descendants"]), int(item["priority"] or 99), item["title"]))

    unresolved_state_counts: Counter[str] = Counter()
    for deps in unresolved.values():
        for dep in deps:
            unresolved_state_counts[str((by_id.get(dep) or {}).get("state") or "missing")] += 1

    workflow_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for task in live:
        workflow = str(task.get("workflow_id") or "unassigned")
        workflow_counts[workflow][str(task.get("state") or "unknown")] += 1

    alert_codes: Counter[str] = Counter()
    open_alert_cards: list[dict[str, Any]] = []
    for alert in alerts:
        if str(alert.get("status") or "open") != "open":
            continue
        code = str(alert.get("code") or "unknown")
        alert_codes[code] += 1
        open_alert_cards.append(
            {
                "id": str(alert.get("id") or ""),
                "severity": str(alert.get("severity") or ""),
                "code": code,
                "resource_id": str(alert.get("resource_id") or ""),
                "message": _redact(str(alert.get("message") or "")),
                "created_at": str(alert.get("created_at") or ""),
            }
        )

    return {
        "status": "DEGRADED" if failed or blocked or open_alert_cards else "HEALTHY",
        "counts": {
            "live_tasks": len(live),
            "running_tasks": len(running),
            "failed_tasks": len(failed),
            "blocked_tasks": len(blocked),
            "open_alerts": len(open_alert_cards),
            "root_blockers": len(root_cards),
            "blocked_without_unresolved_dependencies": len(blocked_without_unresolved),
        },
        "root_blockers": root_cards[:30],
        "blocked_without_unresolved_dependencies": [
            _task_card(task, unresolved=[]) for task in blocked_without_unresolved[:30]
        ],
        "failed_tasks": [
            _task_card(task, unresolved=unresolved.get(str(task.get("id") or ""), [])) for task in failed[:30]
        ],
        "unresolved_dependency_state_counts": dict(sorted(unresolved_state_counts.items())),
        "workflow_state_counts": {key: dict(value) for key, value in sorted(workflow_counts.items())},
        "alert_code_counts": dict(alert_codes.most_common()),
        "open_alerts": open_alert_cards[:40],
        "recommendation": (
            "Repair the highest-impact root blockers first; do not manually unblock downstream tasks. "
            "After each root repair, let the supervisor recompute dependency readiness and verify alert count falls."
            if failed or blocked
            else "No failed/blocked task root cause is present in the live task graph."
        ),
    }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def _read_live_state(db_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        task_rows = conn.execute(
            "SELECT id,parent_id,workflow_id,title,owner_id,state,priority,dependencies,metadata,summary,updated_at "
            "FROM work_items WHERE item_type='task'"
        ).fetchall()
        tasks = [dict(row) for row in task_rows]
        alerts: list[dict[str, Any]] = []
        if _table_exists(conn, "alerts"):
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
            query = "SELECT * FROM alerts" + (" WHERE status='open'" if "status" in columns else "")
            alerts = [dict(row) for row in conn.execute(query).fetchall()]
        return tasks, alerts
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ARCH live company blockers without mutating CompanyStore")
    parser.add_argument("--env-file", default=".env.amaura")
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    args = parser.parse_args(argv)

    load_amaura_env(args.env_file, override=True, require_private_permissions=True)
    data_dir = os.environ.get("AMAURA_DATA_DIR", "").strip()
    if not data_dir:
        raise SystemExit("AMAURA_DATA_DIR is not configured")
    db_path = Path(data_dir).expanduser().resolve() / "amaura.db"
    if not db_path.is_file():
        raise SystemExit(f"CompanyStore database not found: {db_path}")
    if tracked_dirty():
        raise SystemExit("Tracked checkout is dirty; refuse to create exact-SHA blocker evidence")

    tasks, alerts = _read_live_state(db_path)
    result = analyze(tasks, alerts)
    result.update(
        {
            "candidate_sha": git_sha(),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "database": str(db_path),
            "read_only": True,
        }
    )

    evidence_base = Path(args.evidence_dir).expanduser()
    if not evidence_base.is_absolute():
        evidence_base = Path.cwd() / evidence_base
    run_dir = evidence_base / f"{time.strftime('%Y%m%d_%H%M%S')}_ARCH_BLOCKER_AUDIT"
    run_dir.mkdir(parents=True, exist_ok=False)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"Evidence: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
