"""Process-local reliability guards for governed task execution.

These guards do not change authorization or verifier outcomes.  They only make
an already-observed *independent verification rejection* terminal for that
execution attempt so the supervisor cannot blindly re-run the same expensive
coding worker from scratch.  Higher-level bounded DAG replanning remains free
to create a different repair task from the preserved failure evidence.
"""

from __future__ import annotations

from typing import Any

from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.models import TaskState

_ORIGINAL_RUN = GovernedTaskRunner.run

# These messages are emitted only after the coding executor has returned and
# Amaura has begun its independent Git/test verification phase.
_TERMINAL_VERIFICATION_MARKERS = (
    "command failed independent verification:",
    "antigravity changed-file manifest does not match git:",
    "independent verification mutated the repository",
)


def is_independent_verification_failure(reason: str) -> bool:
    clean = " ".join(str(reason).lower().split())
    return any(marker in clean for marker in _TERMINAL_VERIFICATION_MARKERS)


def guarded_task_run(self: GovernedTaskRunner, task_id: str, max_iterations: int = 12) -> dict[str, Any]:
    """Convert verifier rejection from execution retry into durable task failure."""
    result = _ORIGINAL_RUN(self, task_id, max_iterations=max_iterations)
    reason = str(result.get("reason") or "")
    if not (
        result.get("status") == "blocked"
        and result.get("retryable") is True
        and is_independent_verification_failure(reason)
    ):
        return result

    task = self.control.store.get_work_item(task_id)
    if task.get("state") != TaskState.BLOCKED.value:
        return result

    metadata = dict(task.get("metadata") or {})
    metadata.update(
        {
            "retryable": False,
            "verification_failure": True,
            "verification_failure_reason": reason[:1200],
            "execution_retry_suppressed": True,
        }
    )
    self.control.store.update_work_item(task_id, state=TaskState.FAILED.value, metadata=metadata)
    self.control.store.publish_event(
        "task.independent_verification_failed",
        task_id,
        {"reason": reason[:1200], "retryable": False},
    )
    self.control.store.audit(
        "jarvis",
        "independent_verification",
        "task",
        task_id,
        "failed",
        {"reason": reason[:1200], "retryable": False},
    )
    return {
        **result,
        "status": "failed",
        "retryable": False,
        "verification_failure": True,
    }


def install_runtime_guards() -> None:
    """Install execution guard once per process."""
    if getattr(GovernedTaskRunner.run, "_amaura_runtime_guard", False):
        return
    guarded_task_run._amaura_runtime_guard = True  # type: ignore[attr-defined]
    GovernedTaskRunner.run = guarded_task_run  # type: ignore[method-assign]


__all__ = ["guarded_task_run", "install_runtime_guards", "is_independent_verification_failure"]
