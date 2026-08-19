#!/usr/bin/env python3
"""Qualify every safe failed ARCH root blocker on isolated CompanyStore copies.

This harness is read-only with respect to the live CompanyStore. It first runs
the canonical blocker audit, then optionally invokes qualify_arch_root_e2e.py
once per failed root whose action_type is internal_work. Every root receives its
own fresh SQLite backup, external-actions kill switch, evidence directory, and
independent review. No live task state is reset or unblocked by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from jarvis.amaura.runtime import load_amaura_env

_EVIDENCE_LINE = re.compile(r"^Evidence:\s*(.+/summary\.json)\s*$", re.MULTILINE)
_E2E_EVIDENCE_LINE = re.compile(r"^E2E Evidence:\s*(.+/e2e-summary\.json)\s*$", re.MULTILINE)
_SAFE_ACTION_TYPES = {"internal_work"}


def _run(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _git_sha(repo_root: Path) -> str:
    result = _run(["git", "rev-parse", "HEAD"], cwd=repo_root, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _tracked_dirty(repo_root: Path) -> bool:
    result = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_root, timeout=10)
    return result.returncode != 0 or bool(result.stdout.strip())


def _extract_path(pattern: re.Pattern[str], output: str, label: str) -> Path:
    matches = pattern.findall(output)
    if not matches:
        raise RuntimeError(f"{label} did not report its evidence path")
    return Path(matches[-1]).expanduser().resolve()


def _action_types(db_path: Path, task_ids: list[str]) -> dict[str, str]:
    if not task_ids:
        return {}
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        placeholders = ",".join("?" for _ in task_ids)
        rows = connection.execute(
            f"SELECT id,action_type FROM work_items WHERE id IN ({placeholders})",  # noqa: S608 - placeholders only
            tuple(task_ids),
        ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}
    finally:
        connection.close()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"Batch Evidence: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualify all safe ARCH failed roots without mutating live state")
    parser.add_argument("--env-file", default=".env.amaura.v7live")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    parser.add_argument("--run", action="store_true", help="Execute isolated E2E root qualification; default is list-only")
    parser.add_argument("--max-roots", type=int, default=0, help="Optional limit for staged qualification; 0 means all")
    parser.add_argument("--per-root-timeout-seconds", type=int, default=1200)
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    env_file = Path(args.env_file).expanduser().resolve()
    evidence_dir = Path(args.evidence_dir).expanduser().resolve()
    if _tracked_dirty(repo_root):
        raise SystemExit("Tracked checkout is dirty; refuse exact-build company root qualification")
    actual_sha = _git_sha(repo_root)
    if actual_sha != args.expected_sha:
        raise SystemExit(f"Exact-build mismatch: expected {args.expected_sha}, got {actual_sha}")

    load_amaura_env(env_file, override=True, require_private_permissions=True)
    data_dir = os.environ.get("AMAURA_DATA_DIR", "").strip()
    if not data_dir:
        raise SystemExit("AMAURA_DATA_DIR is not configured by the supplied environment file")
    live_db = Path(data_dir).expanduser().resolve() / "amaura.db"
    if not live_db.is_file():
        raise SystemExit(f"Live CompanyStore database not found: {live_db}")

    audit_script = repo_root / "scripts" / "audit_arch_company_blockers.py"
    audit = _run(
        [
            sys.executable,
            str(audit_script),
            "--env-file",
            str(env_file),
            "--evidence-dir",
            str(evidence_dir),
        ],
        cwd=repo_root,
        timeout=120,
    )
    if audit.stdout:
        print(audit.stdout, end="" if audit.stdout.endswith("\n") else "\n")
    if audit.stderr:
        print(audit.stderr, file=sys.stderr, end="" if audit.stderr.endswith("\n") else "\n")
    if audit.returncode != 0:
        raise SystemExit("Blocker audit failed; no root replay was attempted")

    audit_output = (audit.stdout or "") + "\n" + (audit.stderr or "")
    audit_summary_path = _extract_path(_EVIDENCE_LINE, audit_output, "Blocker audit")
    audit_summary = json.loads(audit_summary_path.read_text(encoding="utf-8"))
    roots = list(audit_summary.get("root_blockers") or [])
    failed_root_ids = [
        str(item.get("id") or "")
        for item in roots
        if str(item.get("state") or "") == "failed" and str(item.get("id") or "")
    ]
    action_types = _action_types(live_db, failed_root_ids)
    root_cards: list[dict[str, Any]] = []
    for item in roots:
        task_id = str(item.get("id") or "")
        card = dict(item)
        card["action_type"] = action_types.get(task_id, "unknown")
        card["safe_for_isolated_replay"] = (
            card.get("state") == "failed"
            and card["action_type"] in _SAFE_ACTION_TYPES
            and not list(card.get("unresolved_dependencies") or [])
        )
        root_cards.append(card)

    safe_roots = [item for item in root_cards if item["safe_for_isolated_replay"]]
    safe_roots.sort(
        key=lambda item: (
            -int(item.get("blocked_descendants") or 0),
            int(item.get("priority") or 99),
            str(item.get("title") or ""),
        )
    )
    if args.max_roots > 0:
        safe_roots = safe_roots[: args.max_roots]

    print("===== SAFE ROOT QUALIFICATION PLAN =====")
    print(
        json.dumps(
            {
                "candidate_sha": actual_sha,
                "root_blockers": len(root_cards),
                "safe_failed_internal_roots": len(safe_roots),
                "run_requested": args.run,
                "roots": [
                    {
                        "id": item["id"],
                        "title": item.get("title", ""),
                        "workflow_id": item.get("workflow_id", ""),
                        "blocked_descendants": item.get("blocked_descendants", 0),
                        "action_type": item["action_type"],
                    }
                    for item in safe_roots
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )

    if not args.run:
        return 0

    e2e_script = repo_root / "scripts" / "qualify_arch_root_e2e.py"
    results: list[dict[str, Any]] = []
    for index, root in enumerate(safe_roots, start=1):
        task_id = str(root["id"])
        print(f"===== ROOT {index}/{len(safe_roots)}: {task_id} =====")
        try:
            run = _run(
                [
                    sys.executable,
                    str(e2e_script),
                    "--env-file",
                    str(env_file),
                    "--task-id",
                    task_id,
                    "--expected-sha",
                    actual_sha,
                    "--evidence-dir",
                    str(evidence_dir),
                ],
                cwd=repo_root,
                timeout=max(120, min(args.per_root_timeout_seconds, 3600)),
            )
            if run.stdout:
                print(run.stdout, end="" if run.stdout.endswith("\n") else "\n")
            if run.stderr:
                print(run.stderr, file=sys.stderr, end="" if run.stderr.endswith("\n") else "\n")
            combined = (run.stdout or "") + "\n" + (run.stderr or "")
            summary_path = _extract_path(_E2E_EVIDENCE_LINE, combined, "Root E2E qualification")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            results.append(
                {
                    "task_id": task_id,
                    "title": root.get("title", ""),
                    "blocked_descendants": int(root.get("blocked_descendants") or 0),
                    "status": summary.get("status", "FAIL"),
                    "final_state": summary.get("final_state", ""),
                    "reviewer_model": summary.get("reviewer_model", ""),
                    "reviewer_provider": summary.get("reviewer_provider", ""),
                    "reviewer_distinct_from_worker": summary.get("reviewer_distinct_from_worker", False),
                    "criteria_all_passed": summary.get("criteria_all_passed", False),
                    "evidence": str(summary_path),
                    "returncode": run.returncode,
                }
            )
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            results.append(
                {
                    "task_id": task_id,
                    "title": root.get("title", ""),
                    "blocked_descendants": int(root.get("blocked_descendants") or 0),
                    "status": "FAIL",
                    "final_state": "",
                    "reviewer_model": "",
                    "reviewer_provider": "",
                    "reviewer_distinct_from_worker": False,
                    "criteria_all_passed": False,
                    "evidence": "",
                    "returncode": -1,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    unsafe_roots = [item for item in root_cards if not item["safe_for_isolated_replay"]]
    all_safe_passed = bool(results) and all(item.get("status") == "PASS" and item.get("returncode") == 0 for item in results)
    all_roots_covered = len(results) == len(root_cards) and not unsafe_roots
    overall_pass = all_safe_passed and all_roots_covered
    stamp = time.strftime("%Y%m%d_%H%M%S")
    batch_path = evidence_dir / f"{stamp}_ARCH_COMPANY_ROOT_E2E" / "summary.json"
    report = {
        "qualification": "ARCH_COMPANY_ROOT_E2E",
        "status": "PASS" if overall_pass else "FAIL",
        "candidate_sha": actual_sha,
        "source_writable_connection_opened": False,
        "blocker_audit": str(audit_summary_path),
        "root_blocker_count": len(root_cards),
        "safe_root_count": len(safe_roots),
        "qualified_root_count": len(results),
        "passed_root_count": sum(1 for item in results if item.get("status") == "PASS"),
        "unsafe_or_manual_roots": unsafe_roots,
        "results": results,
    }
    _write_report(batch_path, report)
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
