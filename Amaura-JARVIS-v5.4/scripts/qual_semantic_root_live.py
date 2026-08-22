#!/usr/bin/env python3
"""Resumable live semantic root qualification for Amaura JARVIS.

The expensive worker phase is bounded for interactive qualification. Once a
worker reaches awaiting_review, the isolated state/evidence is persisted so a
reviewer/provider failure can be retried without repeating research.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATE_ROOT = ROOT / ".qualification" / "semantic-root-live"
STATE_FILE = STATE_ROOT / "state.json"


class WorkerDeadlineExceeded(RuntimeError):
    """Raised when the interactive worker qualification exceeds its wall clock."""


def _load_environment() -> None:
    load_dotenv(ROOT / ".env.amaura", override=False)
    load_dotenv(ROOT.parent / ".env.amaura", override=False)


def _apply_fast_worker_profile() -> None:
    """Keep the live root interactive without changing persistent product config."""
    os.environ["AMAURA_NVIDIA_TIMEOUT"] = "15"
    os.environ["AMAURA_NVIDIA_CONNECT_TIMEOUT"] = "5"
    os.environ["AMAURA_NVIDIA_TOTAL_TIMEOUT"] = "20"
    os.environ["AMAURA_NVIDIA_MAX_KEY_ATTEMPTS"] = "1"
    # GovernedTaskRunner uses the worker-specific OmniRoute client rather than
    # the interactive gateway. Keep that independent call inside the same
    # qualification budget; otherwise a single stalled request can exceed the
    # outer live-run deadline before the runner can replan.
    os.environ["AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS"] = "45"
    os.environ["AMAURA_OMNIROUTE_TIMEOUT_SECONDS"] = "20"
    os.environ["AMAURA_OMNIROUTE_MAX_RETRIES"] = "0"


def _write_state(task_id: str) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"task_id": task_id}, indent=2) + "\n", encoding="utf-8")


def _read_state() -> str:
    if not STATE_FILE.exists():
        return ""
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("task_id") or "").strip()


def _print_evidence(evidence: list[dict[str, Any]]) -> None:
    print("\n========== EVIDENCE ==========")
    print("EVIDENCE COUNT:", len(evidence))
    for index, item in enumerate(evidence, start=1):
        print(
            f"{index:02d}. type={item.get('type')} tool={item.get('tool')} "
            f"success={item.get('success')} ref={item.get('reference')}"
        )


def _contract_checks(
    execution: dict[str, Any], reviewed: dict[str, Any], stored: dict[str, Any]
) -> dict[str, bool]:
    contract = json.loads(stored["summary"])
    source_register = contract.get("source_register") or []
    criteria_rows = contract.get("criteria") or []
    evidence = execution.get("evidence") or stored.get("evidence") or []

    successful_public_evidence = [
        item
        for item in evidence
        if item.get("success") is True
        and (
            str(item.get("tool") or "").startswith("web_")
            or str(item.get("tool") or "").startswith("browser_")
            or str(item.get("tool") or "")
            in {
                "search_web",
                "search_web_fast",
                "search_web_slow",
                "deep_research",
                "summarize_url",
            }
        )
    ]
    public_refs = {
        str(item["reference"])
        for item in successful_public_evidence
        if item.get("reference")
    }
    registered_refs = {
        str(item["evidence_ref"])
        for item in source_register
        if item.get("evidence_ref")
    }

    receipt = execution.get("model_execution_receipt") or {}
    review_rows = reviewed.get("criteria") or []
    deterministic = reviewed.get("deterministic_review") or {}
    originality = (
        criteria_rows[2].get("originality_rationale") or {}
        if len(criteria_rows) >= 3
        else {}
    )
    worker_models = set(receipt.get("models_used") or [])

    return {
        "completion_gate": int(receipt.get("completion_gate_attempts") or 0) >= 1,
        "public_evidence": bool(successful_public_evidence),
        "source_register": bool(public_refs) and public_refs.issubset(registered_refs),
        "amaura_relevance": len(criteria_rows) >= 2
        and bool(criteria_rows[1].get("amaura_relevance")),
        "originality": all(
            bool(originality.get(field))
            for field in (
                "observed_patterns",
                "category_level_ideas",
                "amaura_differentiation",
                "copying_avoidance",
            )
        ),
        "reviewer_independent": bool(reviewed.get("reviewer_model"))
        and reviewed["reviewer_model"] not in worker_models,
        "deterministic_review": deterministic.get("approve") is True
        and not (deterministic.get("findings") or []),
        "independent_review": reviewed.get("approve") is True
        and len(review_rows) == 3
        and all(row.get("passed") is True for row in review_rows),
    }


def _run_worker_bounded(runner, task_id: str, *, max_iterations: int, deadline_seconds: int):
    done = threading.Event()

    def heartbeat() -> None:
        elapsed = 0
        while not done.wait(30):
            elapsed += 30
            print(
                f"[heartbeat] worker still running: {elapsed}s / {deadline_seconds}s max",
                flush=True,
            )

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()

    previous_handler = None
    timer_enabled = hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")

    def deadline_handler(_signum, _frame) -> None:
        raise WorkerDeadlineExceeded(
            f"Live worker exceeded the {deadline_seconds}s wall-clock qualification budget"
        )

    try:
        if timer_enabled:
            previous_handler = signal.signal(signal.SIGALRM, deadline_handler)
            signal.setitimer(signal.ITIMER_REAL, float(deadline_seconds))
        return runner.run(task_id, max_iterations=max_iterations)
    finally:
        if timer_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            if previous_handler is not None:
                signal.signal(signal.SIGALRM, previous_handler)
        done.set()


def main() -> int:
    global STATE_ROOT, STATE_FILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="discard prior isolated qualification state")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=STATE_ROOT,
        help="isolated qualification state directory (default: %(default)s)",
    )
    parser.add_argument(
        "--check-imports",
        action="store_true",
        help="verify standalone script imports without starting a qualification run",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=12,
        help="bounded worker model/tool iterations (1-20; default: 12)",
    )
    parser.add_argument(
        "--worker-deadline-seconds",
        type=int,
        default=300,
        help="worker wall-clock budget in seconds (60-600; default: 300)",
    )
    args = parser.parse_args()
    if not 1 <= args.max_iterations <= 20:
        parser.error("--max-iterations must be between 1 and 20")
    if not 60 <= args.worker_deadline_seconds <= 600:
        parser.error("--worker-deadline-seconds must be between 60 and 600")

    STATE_ROOT = args.state_root.expanduser().resolve()
    STATE_FILE = STATE_ROOT / "state.json"

    if args.reset and STATE_ROOT.exists():
        shutil.rmtree(STATE_ROOT)

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _load_environment()
    _apply_fast_worker_profile()
    os.environ["AMAURA_EVIDENCE_DIR"] = str(STATE_ROOT / "evidence")

    review_mode = os.environ.setdefault("AMAURA_REVIEW_MODE", "omniroute").strip().lower()
    if review_mode == "cloud":
        review_model = os.environ.get("AMAURA_CLOUD_REVIEW_MODEL", "").strip()
    else:
        review_model = os.environ.setdefault("AMAURA_OMNIROUTE_REVIEW_MODEL", "auto/best-reasoning").strip()

    from jarvis.amaura.control_plane import AmauraControlPlane
    from jarvis.amaura.executor import GovernedReviewRunner, GovernedTaskRunner

    if args.check_imports:
        print("JARVIS IMPORT: OK")
        return 0

    print("\n========== LIVE SEMANTIC ROOT QUALIFICATION ==========")
    print("STATE DIR:", STATE_ROOT)
    print("WORKER ITERATION BUDGET:", args.max_iterations)
    print("WORKER WALL-CLOCK BUDGET:", f"{args.worker_deadline_seconds}s")
    print("NVIDIA TURN PROFILE: 15s request / 20s total / 1 credential")
    print("REVIEW MODE:", review_mode)
    print("REQUESTED REVIEWER:", review_model or "provider default")

    control = AmauraControlPlane(
        STATE_ROOT / "root.db",
        audit_checkpoint_path=STATE_ROOT / "audit.checkpoint",
    )

    try:
        task_id = _read_state()
        task: dict[str, Any] | None = None
        if task_id:
            try:
                task = control.store.get_work_item(task_id)
            except Exception:
                task = None

        if task is None:
            programme = control.create_program(
                objective=(
                    "Research current AI assistant, content, and product competitors and audience demand for an "
                    "Amaura founder-facing content brief. Use multiple credible current public sources. Produce "
                    "evidence sufficient for a complete source register, explain the specific relevance to Amaura, "
                    "and explicitly separate category-level lessons from competitor-specific wording, branding, "
                    "proprietary flows, or other expression we must not copy. Stop researching once 6-8 distinct "
                    "successful public sources are enough to support all three acceptance criteria; then synthesize."
                ),
                success_metric=(
                    "The content_factory research task passes all three independent-review criteria with immutable "
                    "public-source evidence."
                ),
                workflow_key="content_factory",
                inputs={
                    "campaign_id": "semantic-root-live-resumable",
                    "audience": "founders evaluating AI executive and automation systems",
                    "business_objective": "evidence-backed Amaura positioning without competitor copying",
                },
            )
            task = programme["tasks"][0]
            task_id = task["id"]
            _write_state(task_id)

        print("TASK ID:", task_id)
        print("STATE:", task["state"])
        print("CRITERIA:", json.dumps(task["acceptance_criteria"], indent=2))

        execution: dict[str, Any]
        if task["state"] == "awaiting_review":
            print("\nWorker phase already complete; resuming directly at independent review.")
            stored = control.store.get_work_item(task_id)
            execution = {
                "status": stored["state"],
                "evidence": stored.get("evidence") or [],
                "model_execution_receipt": {},
            }
            for item in stored.get("evidence") or []:
                if item.get("type") != "model_execution_receipt" or not item.get("reference"):
                    continue
                try:
                    execution["model_execution_receipt"] = json.loads(
                        control.evidence.get_text(item["reference"])
                    )
                except Exception:
                    pass
        elif task["state"] in {"assigned", "blocked", "in_progress"}:
            if task["state"] == "in_progress":
                print(
                    "\nPrevious worker run ended before submission. The task record is reusable, "
                    "but the unfinished worker conversation is not checkpointed; restarting with a fast plan."
                )
                metadata = dict(task.get("metadata") or {})
                metadata["replan_instruction"] = (
                    "A previous qualification worker run ended before submission. This retry starts with a fresh "
                    "worker conversation. Do not over-research. Target 6-8 distinct successful public sources, "
                    "avoid redundant searches and repeated fetches, and once those sources support the source "
                    "register, Amaura relevance, and originality/non-copying criteria, stop tool use immediately "
                    "and return the draft summary so JARVIS can run completion synthesis."
                )
                task = control.store.update_work_item(task_id, metadata=metadata)

            print("\n========== WORKER ==========")
            execution = _run_worker_bounded(
                GovernedTaskRunner(control),
                task_id,
                max_iterations=args.max_iterations,
                deadline_seconds=args.worker_deadline_seconds,
            )
            print("WORKER STATUS:", execution["status"])
            print("ITERATIONS:", execution.get("iterations"))
            receipt = execution.get("model_execution_receipt") or {}
            print("COMPLETION GATE ATTEMPTS:", receipt.get("completion_gate_attempts"))
            print("WORKER MODELS:", json.dumps(receipt.get("models_used") or [], indent=2))
            _print_evidence(execution.get("evidence") or [])
        else:
            print("Task is already terminal:", task["state"])
            return 2

        stored = control.store.get_work_item(task_id)
        if stored["state"] != "awaiting_review":
            print("ROOT_QUALIFICATION: FAIL")
            print("Worker did not reach awaiting_review; task record preserved for inspection.")
            return 1

        os.environ["AMAURA_OMNIROUTE_FALLBACK_MODEL"] = ""

        print("\n========== INDEPENDENT REVIEW ==========")
        print("REQUESTED REVIEWER:", review_model or "provider default")
        reviewed = GovernedReviewRunner(control).run(task_id)
        print("REVIEW APPROVE:", reviewed["approve"])
        print("REVIEW STATE:", reviewed["state"])
        print("REVIEW MODEL:", reviewed["reviewer_model"])
        print("REVIEW PROVIDER:", reviewed["reviewer_provider"])
        print("REVIEW FINDINGS:", reviewed["findings"])
        print("CRITERIA:", json.dumps(reviewed.get("criteria") or [], indent=2))

        stored = control.store.get_work_item(task_id)
        checks = _contract_checks(execution, reviewed, stored)
        print("\n========== CONTRACT CHECKS ==========")
        for name, passed in checks.items():
            print(f"{name}: {passed}")

        passed = all(checks.values())
        print("\n========== FINAL VERDICT ==========")
        print("ROOT_QUALIFICATION:", "PASS" if passed else "FAIL")
        if passed:
            print("The persistent qualification state may be removed with --reset before a future fresh run.")
            return 0
        print("State preserved. Re-run this same command to resume completed phases.")
        return 1
    except BaseException as exc:
        print("\n========== ROOT QUALIFICATION ERROR ==========")
        print("ERROR TYPE:", type(exc).__name__)
        print("ERROR:", str(exc))
        current = None
        try:
            current = control.store.get_work_item(_read_state()) if _read_state() else None
        except Exception:
            current = None
        if current and current.get("state") == "awaiting_review":
            print("Worker phase is complete and preserved. Re-run this same command to retry review only.")
        else:
            print(
                "Task record is preserved, but an unfinished worker conversation is not checkpointed. "
                "The next run will restart worker context under the same bounded fast profile."
            )
        return 2
    finally:
        control.close()


if __name__ == "__main__":
    sys.exit(main())
