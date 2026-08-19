#!/usr/bin/env python3
"""Qualify one real ARCH root blocker end-to-end on an isolated CompanyStore copy.

The source CompanyStore is never opened for writing. Worker execution is first
performed by replay_arch_root_task.py, which creates a read-only SQLite backup
and arms only the selected safe internal root in that copy. This harness then
runs independent review against the same copy and requires completion, distinct
worker/reviewer model provenance, criterion coverage, and intact store/audit
integrity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from jarvis.amaura.runtime import load_amaura_env

_EVIDENCE_LINE = re.compile(r"^Evidence:\s*(.+/summary\.json)\s*$", re.MULTILINE)


def _extract_summary_path(output: str) -> Path:
    matches = _EVIDENCE_LINE.findall(output)
    if not matches:
        raise RuntimeError("Worker replay did not report its summary.json path")
    return Path(matches[-1]).expanduser().resolve()


def _configure_copy_environment(qualification_dir: Path) -> Path | None:
    os.environ["AMAURA_DATA_DIR"] = str((qualification_dir / "data").resolve())
    os.environ["AMAURA_EVIDENCE_DIR"] = str((qualification_dir / "evidence").resolve())
    os.environ["AMAURA_HANDOFF_DIR"] = str((qualification_dir / "handoffs").resolve())
    os.environ["AMAURA_BACKUP_DIR"] = str((qualification_dir / "backups").resolve())
    os.environ["JARVIS_DATA_DIR"] = str((qualification_dir / "jarvis-data").resolve())
    os.environ["JARVIS_LEGACY_TOOL_MODE"] = "disabled"
    os.environ["JARVIS_ENABLE_LEGACY_DIRECT_TOOLS"] = "0"
    os.environ["AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS"] = "0"
    checkpoint = qualification_dir / "trust" / "audit-head.json"
    if checkpoint.is_file():
        os.environ["AMAURA_AUDIT_CHECKPOINT_PATH"] = str(checkpoint.resolve())
        return checkpoint.resolve()
    os.environ.pop("AMAURA_AUDIT_CHECKPOINT_PATH", None)
    return None


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"E2E Evidence: {path}")


def _worker_models(reviewer: Any, task: dict[str, Any]) -> list[str]:
    values = reviewer._worker_models_from_evidence(task)
    return sorted(str(value) for value in values if str(value).strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualify one ARCH root worker→evidence→review→completion lifecycle")
    parser.add_argument("--env-file", default=".env.amaura.v7live")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--worker-timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)

    env_file = Path(args.env_file).expanduser().resolve()
    evidence_dir = Path(args.evidence_dir).expanduser().resolve()
    replay_script = Path(__file__).resolve().with_name("replay_arch_root_task.py")
    if not replay_script.is_file():
        raise SystemExit(f"Missing replay harness: {replay_script}")

    worker_command = [
        sys.executable,
        str(replay_script),
        "--env-file",
        str(env_file),
        "--task-id",
        args.task_id,
        "--expected-sha",
        args.expected_sha,
        "--evidence-dir",
        str(evidence_dir),
        "--max-iterations",
        str(args.max_iterations),
    ]
    try:
        worker = subprocess.run(
            worker_command,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(60, min(args.worker_timeout_seconds, 3600)),
        )
    except subprocess.TimeoutExpired as exc:
        print(exc.stdout or "")
        print(exc.stderr or "", file=sys.stderr)
        raise SystemExit("FAIL: isolated worker replay exceeded its qualification timeout") from exc

    if worker.stdout:
        print(worker.stdout, end="" if worker.stdout.endswith("\n") else "\n")
    if worker.stderr:
        print(worker.stderr, file=sys.stderr, end="" if worker.stderr.endswith("\n") else "\n")

    combined = (worker.stdout or "") + "\n" + (worker.stderr or "")
    try:
        worker_summary_path = _extract_summary_path(combined)
    except RuntimeError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    if not worker_summary_path.is_file():
        raise SystemExit(f"FAIL: worker summary does not exist: {worker_summary_path}")

    worker_summary = json.loads(worker_summary_path.read_text(encoding="utf-8"))
    qualification_dir = worker_summary_path.parent
    e2e_report_path = qualification_dir / "e2e-summary.json"
    if worker.returncode != 0 or worker_summary.get("status") != "PASS":
        report = {
            "qualification": "ARCH_ROOT_E2E",
            "status": "FAIL",
            "stage": "worker_replay",
            "task_id": args.task_id,
            "git_sha": args.expected_sha,
            "worker_returncode": worker.returncode,
            "worker_summary": str(worker_summary_path),
        }
        _write_report(e2e_report_path, report)
        return 1

    load_amaura_env(env_file, override=True, require_private_permissions=True)
    copied_db = qualification_dir / "data" / "amaura.db"
    if not copied_db.is_file():
        raise SystemExit(f"FAIL: copied CompanyStore is missing: {copied_db}")
    copied_checkpoint = _configure_copy_environment(qualification_dir)

    # Import only after the isolated environment is installed. Importing the
    # package installs ARCH's automatic hosted reviewer-diversity decorator.
    from jarvis.amaura.control_plane import AmauraControlPlane
    from jarvis.amaura.executor import GovernedReviewRunner
    from jarvis.amaura.models import TaskState

    control = AmauraControlPlane(db_path=copied_db, audit_checkpoint_path=copied_checkpoint)
    try:
        before = control.store.get_work_item(args.task_id)
        integrity_before = control.store.integrity_check()
        reviewer = GovernedReviewRunner(control)
        worker_models = _worker_models(reviewer, before)
        if before.get("state") != TaskState.AWAITING_REVIEW.value:
            raise RuntimeError(f"Worker replay did not leave task awaiting review: {before.get('state')!r}")
        if not integrity_before.get("ok"):
            raise RuntimeError(f"Copied CompanyStore failed integrity before review: {integrity_before}")

        review: dict[str, Any] = {}
        review_error: Exception | None = None
        try:
            review = reviewer.run(args.task_id)
        except Exception as exc:  # noqa: BLE001 - qualification must persist exact failure evidence
            review_error = exc

        final = control.store.get_work_item(args.task_id)
        integrity_after = control.store.integrity_check()
        reviewer_model = str(review.get("reviewer_model") or "").strip()
        reviewer_provider = str(review.get("reviewer_provider") or "").strip()
        distinct = bool(reviewer_model) and reviewer_model not in set(worker_models)
        criteria = list(review.get("criteria") or [])
        criteria_pass = bool(criteria) and all(bool(item.get("passed")) for item in criteria)
        completed = final.get("state") == TaskState.COMPLETED.value
        passed = (
            review_error is None
            and bool(review.get("approve"))
            and completed
            and distinct
            and criteria_pass
            and bool(integrity_after.get("ok"))
        )

        report = {
            "qualification": "ARCH_ROOT_E2E",
            "status": "PASS" if passed else "FAIL",
            "stage": "completed" if passed else "independent_review",
            "task_id": args.task_id,
            "git_sha": args.expected_sha,
            "source_writable_connection_opened": False,
            "worker_summary": str(worker_summary_path),
            "worker_models": worker_models,
            "successful_tools": worker_summary.get("successful_tools") or [],
            "successful_tool_evidence_count": worker_summary.get("successful_tool_evidence_count", 0),
            "reviewer_model": reviewer_model,
            "reviewer_provider": reviewer_provider,
            "requested_reviewer_model": str(review.get("requested_reviewer_model") or ""),
            "reviewer_distinct_from_worker": distinct,
            "review_approve": bool(review.get("approve")),
            "criterion_count": len(criteria),
            "criteria_all_passed": criteria_pass,
            "final_state": str(final.get("state") or ""),
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "review_error_type": type(review_error).__name__ if review_error is not None else "",
            "review_error": str(review_error)[:2000] if review_error is not None else "",
        }
        _write_report(e2e_report_path, report)
        return 0 if passed else 1
    finally:
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
