"""Durable background execution service for JARVIS dynamic missions.

Mission submission is decoupled from execution. The runner scans CompanyStore
for runnable dynamic goals and advances them through the governed Supervisor.
Transient failures back off; configuration/provider failures enter explicit
waiting states instead of spinning every polling interval.

v7 convergence note: MissionRunner is no longer an independent company-level
scheduler. It shares the canonical company-runtime leader lease and exposes a
``leader_owned`` compatibility path so AutonomousCompanyRuntime can advance
missions while already holding that lease.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.amaura.brain import JarvisBrain
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.portfolio import PortfolioArbitrator
from jarvis.amaura.runtime_lease import company_runtime_leader_lock

TERMINAL_STATES = {TaskState.COMPLETED.value, TaskState.CANCELLED.value, TaskState.FAILED.value}


@dataclass(slots=True)
class MissionRunnerResult:
    goal_id: str
    state: str
    advanced: bool
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"goal_id": self.goal_id, "state": self.state, "advanced": self.advanced, "detail": self.detail}


class MissionRunner:
    """Advance runnable JARVIS missions without bypassing policy or approvals."""

    def __init__(self, control: AmauraControlPlane) -> None:
        self.control = control
        self.portfolio = PortfolioArbitrator(control)
        self._local_lock = threading.RLock()

    @contextlib.contextmanager
    def _leader_lock(self):
        """Share the single canonical company-runtime leadership lease."""
        with company_runtime_leader_lock(self.control) as leader:
            yield leader

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None

    @classmethod
    def _is_runnable(cls, goal: dict[str, Any]) -> bool:
        metadata = dict(goal.get("metadata") or {})
        if not metadata.get("dynamic_goal") or metadata.get("mission_runnable") is not True:
            return False
        if metadata.get("mission_paused") is True or metadata.get("antigravity_handoff") is True:
            return False
        if goal.get("state") in TERMINAL_STATES or goal.get("state") == TaskState.DRAFT.value:
            return False
        next_attempt = cls._parse_time(metadata.get("runner_next_attempt_at"))
        if next_attempt and next_attempt > datetime.now(UTC):
            return False
        return True

    def runnable_goals(self, *, limit: int = 100) -> list[dict[str, Any]]:
        goals = self.control.store.list_work_items(item_type="programme", limit=max(1, min(limit, 500)))
        runnable = [goal for goal in goals if self._is_runnable(goal)]
        return self.portfolio.rank_goals(runnable)

    @staticmethod
    def _failure_class(exc: Exception) -> tuple[str, int]:
        text = str(exc).lower()
        configuration_terms = (
            "not configured",
            "not installed",
            "invalid command",
            "requires",
            "authentication",
            "sign in",
            "login",
            "no isolation runtime",
            "sandbox",
            "missing credential",
        )
        provider_terms = ("rate limit", "429", "quota", "overloaded", "provider", "timeout", "temporarily unavailable")
        if any(term in text for term in configuration_terms):
            return "waiting_configuration", 60
        if any(term in text for term in provider_terms):
            return "waiting_provider", 15
        return "waiting_retry", 5

    def _record_failure(self, goal_id: str, exc: Exception) -> dict[str, Any]:
        goal = self.control.store.get_work_item(goal_id)
        metadata = dict(goal.get("metadata") or {})
        failures = int(metadata.get("runner_failure_count", 0) or 0) + 1
        state, base = self._failure_class(exc)
        delay = min(base * (2 ** min(failures - 1, 6)), 900)
        next_attempt = datetime.now(UTC) + timedelta(seconds=delay)
        metadata.update(
            {
                "runner_status": state,
                "runner_failure_count": failures,
                "runner_last_error": str(exc)[:4000],
                "runner_last_error_at": datetime.now(UTC).isoformat(),
                "runner_next_attempt_at": next_attempt.isoformat(),
            }
        )
        self.control.store.update_work_item(goal_id, metadata=metadata)
        self.control.store.publish_event(
            "jarvis.mission.runner_error",
            goal_id,
            {"error": str(exc)[:4000], "class": state, "retry_in_seconds": delay},
        )
        return {
            "error": str(exc),
            "class": state,
            "retry_in_seconds": delay,
            "next_attempt_at": next_attempt.isoformat(),
        }

    def _clear_failure(self, goal_id: str) -> None:
        goal = self.control.store.get_work_item(goal_id)
        metadata = dict(goal.get("metadata") or {})
        metadata["runner_last_advanced_at"] = datetime.now(UTC).isoformat()
        if not any(k in metadata for k in ("runner_status", "runner_last_error", "runner_next_attempt_at")):
            self.control.store.update_work_item(goal_id, metadata=metadata)
            return
        metadata["runner_status"] = "running"
        metadata["runner_failure_count"] = 0
        metadata.pop("runner_last_error", None)
        metadata.pop("runner_last_error_at", None)
        metadata.pop("runner_next_attempt_at", None)
        self.control.store.update_work_item(goal_id, metadata=metadata)

    def _tick_locked(self, *, max_goals: int = 3) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        scan_limit = max(100, max_goals * 20)
        for goal in self.runnable_goals(limit=scan_limit)[: max(1, min(max_goals, 20))]:
            goal_id = str(goal["id"])
            try:
                before = JarvisBrain(self.control).status(goal_id)
                if before["state"] in {"completed", "awaiting_approval", "cancelled", "held", "failed"}:
                    results.append(MissionRunnerResult(goal_id, before["state"], False, {}).to_dict())
                    continue
                execution = JarvisBrain(self.control).run_goal(goal_id, max_ticks=1, auto_replan=True)
                self._clear_failure(goal_id)
                results.append(
                    MissionRunnerResult(goal_id, execution.state, bool(execution.ticks), execution.to_dict()).to_dict()
                )
            except (GovernanceError, KeyError, ValueError, RuntimeError, OSError) as exc:
                detail = self._record_failure(goal_id, exc)
                results.append(MissionRunnerResult(goal_id, detail["class"], False, detail).to_dict())
        return {"status": "advanced" if results else "idle", "missions": results}

    def tick(self, *, max_goals: int = 3, leader_owned: bool = False) -> dict[str, Any]:
        """Advance bounded dynamic goals under the canonical runtime lease.

        ``leader_owned`` is reserved for ``AutonomousCompanyRuntime`` while it
        already owns the company lease. External callers keep the default and
        therefore cannot establish a second scheduling authority.
        """
        with self._local_lock:
            if leader_owned:
                return self._tick_locked(max_goals=max_goals)
            with self._leader_lock() as leader:
                if leader is False:
                    return {
                        "status": "standby",
                        "missions": [],
                        "reason": "another company runtime process holds the leader lease",
                    }
                return self._tick_locked(max_goals=max_goals)

    def run_goal_until_terminal(
        self,
        goal_id: str,
        *,
        timeout_seconds: float = 300.0,
        poll_seconds: float = 0.25,
        max_ticks: int = 100,
        leader_owned: bool = False,
    ) -> dict[str, Any]:
        """Synchronously drive or wait for a goal until terminal/blocked state."""
        import time

        from jarvis.amaura.cognition import ExecutiveKernel

        start_time = time.monotonic()
        brain = JarvisBrain(self.control)
        terminal_or_blocked = {
            "completed",
            "awaiting_approval",
            "failed",
            "cancelled",
            "held",
            "handoff_required",
            "authorization_required",
            "rejected",
            "reference_required",
        }

        ticks_executed = 0
        while True:
            try:
                current_status = brain.status(goal_id)
            except Exception as exc:
                return {
                    "goal_id": goal_id,
                    "state": "failed",
                    "error": str(exc),
                    "message": f"Mission {goal_id} failed to query status: {exc}",
                    "status": {},
                }

            state = current_status.get("state", "queued")
            if state in terminal_or_blocked:
                return {
                    "goal_id": goal_id,
                    "state": state,
                    "status": current_status,
                    "message": ExecutiveKernel._mission_message(current_status),
                    "ticks_executed": ticks_executed,
                }

            if (time.monotonic() - start_time) >= timeout_seconds or ticks_executed >= max_ticks:
                return {
                    "goal_id": goal_id,
                    "state": "timeout",
                    "status": current_status,
                    "message": f"Mission {goal_id} timed out before reaching a terminal state.",
                    "ticks_executed": ticks_executed,
                }

            with self._local_lock:
                manager = contextlib.nullcontext(True) if leader_owned else self._leader_lock()
                with manager as leader:
                    if leader is False:
                        time.sleep(max(0.05, poll_seconds))
                        continue
                    try:
                        execution = brain.run_goal(goal_id, max_ticks=1, auto_replan=True)
                        self._clear_failure(goal_id)
                        ticks_executed += len(execution.ticks) if execution.ticks else 1
                        if execution.ticks and execution.state not in terminal_or_blocked:
                            time.sleep(0.02)
                            continue
                    except (GovernanceError, KeyError, ValueError, RuntimeError, OSError) as exc:
                        self._record_failure(goal_id, exc)
                        ticks_executed += 1

            time.sleep(max(0.05, poll_seconds))

    def run_forever(
        self, *, poll_seconds: float = 2.0, max_goals: int = 3, stop_event: threading.Event | None = None
    ) -> None:
        """Compatibility service loop sharing company-runtime leadership."""
        stop = stop_event or threading.Event()
        delay = max(0.25, min(float(poll_seconds), 60.0))
        while not stop.is_set():
            self.tick(max_goals=max_goals)
            stop.wait(delay)


__all__ = ["MissionRunner", "MissionRunnerResult"]
