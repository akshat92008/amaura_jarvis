"""Safe autonomous company loop for Amaura Labs.

Autopilot never broadens authority.  It creates only idempotent internal cadence
programmes, advances one governed supervisor unit, and returns a founder briefing.
External publication, messaging, deployment, spending and strategic commitments
remain approval-gated by the existing control plane.
"""

from __future__ import annotations

import os
from contextlib import closing, contextmanager
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
from jarvis.amaura.cognition import ProactiveCognition, WorldModel
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.mission_control import MissionControl
from jarvis.amaura.supervisor import AmauraSupervisor


class AutonomousCompanyRuntime:
    def __init__(
        self,
        control: AmauraControlPlane,
        *,
        worker_id: str = "amaura-autopilot",
        automatic_reviews: bool = True,
    ):
        self.control = control
        self.supervisor = AmauraSupervisor(
            control,
            worker_id=worker_id,
            automatic_reviews=automatic_reviews,
        )
        self.mission = MissionControl(control)
        self.company = CompanyAutonomyEngine(control, worker_id=worker_id)

    @contextmanager
    def _leader_lock(self):
        """Single-writer company-autopilot lease shared by desktop and daemon runtimes."""
        if os.name != "posix":
            yield True
            return
        import fcntl
        lock_path = self.control.store.db_path.with_suffix(".company-autopilot.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _week_key(now: datetime) -> str:
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"

    def ensure_operating_cadence(self, now: datetime | None = None) -> list[dict[str, Any]]:
        if self.control.store.get_control("autopilot_enabled", "1") != "1":
            return []
        now = now or datetime.now(UTC)
        week_key = self._week_key(now)
        if any(
            objective.get("workflow_key") == "company_operating_review"
            and objective.get("status") == "active"
            for objective in self.control.store.list_objectives(limit=1000)
        ):
            return []
        active = self.control.store.list_work_items(item_type="programme", limit=1000)
        for programme in active:
            if (
                programme.get("workflow_id") == "company_operating_review"
                and (programme.get("metadata") or {}).get("inputs", {}).get("review_window") == week_key
                and programme.get("state") not in {"failed", "cancelled"}
            ):
                return []
        created = self.control.create_program(
            objective=f"Run Amaura Labs operating review for {week_key}",
            success_metric="Founder receives an evidenced, budget-aware priority decision",
            workflow_key="company_operating_review",
            title=f"Weekly operating review — {week_key}",
            priority=2,
            inputs={"review_window": week_key, "cadence_key": week_key},
        )
        return [created]


    def ensure_daily_backup(self, now: datetime | None = None) -> dict[str, Any]:
        """Create and verify one durable backup per UTC day.

        Backups are local, transactionally consistent and safe to run from the
        continuous company loop. A fixed daily destination plus atomic replace
        makes concurrent workers harmless: the final artefact is always a full
        verified SQLite database rather than a partially written file.
        """
        now = now or datetime.now(UTC)
        if os.environ.get("AMAURA_AUTOMATIC_BACKUPS", "1") != "1":
            return {"status": "disabled"}

        day = now.strftime("%Y%m%d")
        backup_dir_value = os.environ.get("AMAURA_BACKUP_DIR", "").strip()
        if backup_dir_value:
            backup_dir = Path(backup_dir_value).expanduser().resolve()
        else:
            data_dir = Path(os.environ.get("AMAURA_DATA_DIR", ".amaura-data")).expanduser().resolve()
            backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        destination = backup_dir / f"amaura-{day}.db"
        control_key = "autonomy.last_automatic_backup_date"

        if self.control.store.get_control(control_key, "") == day and destination.exists():
            return {
                "status": "current",
                "date": day,
                "path": str(destination),
                "bytes": destination.stat().st_size,
            }

        temporary = backup_dir / f".amaura-{day}-{uuid.uuid4().hex}.tmp"
        try:
            self.control.store.backup(temporary)
            with closing(sqlite3.connect(temporary)) as connection:
                integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != ["ok"] or foreign_keys:
                raise RuntimeError(
                    f"Automatic backup verification failed: integrity={integrity!r}, "
                    f"foreign_keys={len(foreign_keys)}"
                )
            os.replace(temporary, destination)
            self.control.store.set_control(control_key, day, "amaura-autopilot")

            retention_days = max(1, min(int(os.environ.get("AMAURA_BACKUP_RETENTION_DAYS", "14")), 3650))
            cutoff = now - timedelta(days=retention_days)
            removed: list[str] = []
            for candidate in backup_dir.glob("amaura-????????.db"):
                if candidate == destination:
                    continue
                try:
                    modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
                except OSError:
                    continue
                if modified < cutoff:
                    candidate.unlink(missing_ok=True)
                    removed.append(str(candidate))

            result = {
                "status": "created",
                "date": day,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "integrity": integrity,
                "foreign_key_violations": len(foreign_keys),
                "retention_days": retention_days,
                "removed": removed,
            }
            self.control.store.publish_event("company.backup.completed", day, result)
            self.control.store.audit(
                "amaura-autopilot",
                "automatic_backup",
                "backup",
                str(destination),
                "allowed",
                {"date": day, "bytes": result["bytes"]},
            )
            return result
        finally:
            temporary.unlink(missing_ok=True)

    def _tick_locked(
        self,
        *,
        now: datetime | None = None,
        max_work_units: int = 1,
        max_new_programmes: int | None = None,
        max_signals: int = 3,
    ) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        run = self.control.store.start_autonomy_run(
            worker_id=str(getattr(self.supervisor, "worker_id", "amaura-autopilot")),
            mode="company_tick",
        )
        backup = self.ensure_daily_backup(now)
        enabled = self.control.store.get_control("autopilot_enabled", "1") == "1"
        if not enabled:
            result = {
                "status": "paused",
                "run_id": run["id"],
                "backup": backup,
                "cadence_programmes_created": [],
                "objective_programmes_created": [],
                "signals_detected": [],
                "signal_programmes_created": [],
                "objective_progress_updates": [],
                "publications_enqueued": [],
                "circuit_breakers": [],
                "proactive_insights": ProactiveCognition(self.control).scan(),
                "world": WorldModel(self.control).refresh(),
                "executions": [],
                "execution": {"status": "paused"},
                "company": self.company.status(),
                "portfolio": self.mission.portfolio(),
                "briefing": self.control.daily_briefing(),
                "supervisor": self.supervisor.status(),
            }
            self.control.store.finish_autonomy_run(run["id"], status="paused", result=result)
            return result

        try:
            progress_updates = self.mission.sync_completed_programmes()
            signals_detected = self.company.detect_signals(now=now)
            signal_programmes = self.company.process_signals(now=now, max_signals=max_signals)
            created = self.ensure_operating_cadence(now)
            objective_programmes = self.mission.plan_due_work(
                now=now, max_new_programmes=max_new_programmes
            )
            publications = self.control.distribution.dispatch_due(now=now, limit=5)
            units = max(1, min(int(max_work_units), 20))
            executions: list[dict[str, Any]] = []
            for _ in range(units):
                tick_result = self.supervisor.tick()
                executions.append(tick_result)
                if tick_result.get("status") in {"idle", "review_deferred"}:
                    break
            execution = executions[-1] if executions else {"status": "idle"}
            progress_updates.extend(self.mission.sync_completed_programmes())
            circuit_breakers = self.company.evaluate_circuit_breakers(now=now)
            world = WorldModel(self.control).refresh()
            proactive_insights = ProactiveCognition(self.control).scan()
            from jarvis.amaura.ventures_cashflow import CashflowEngine
            venture_cashflow = CashflowEngine(self.control).tick(
                actor="jarvis", proposal_limit=max(1, min(int(os.environ.get("AMAURA_VENTURE_PROPOSALS_PER_CYCLE", "4")), 20))
            )
            result = {
                "status": "ok",
                "run_id": run["id"],
                "backup": backup,
                "cadence_programmes_created": [item["programme"]["id"] for item in created],
                "objective_programmes_created": [
                    item["programme"]["id"] for item in objective_programmes
                ],
                "signals_detected": [item["id"] for item in signals_detected],
                "signal_programmes_created": [
                    item["programme"]["programme"]["id"] for item in signal_programmes
                ],
                "objective_progress_updates": progress_updates,
                "publications_enqueued": [item["id"] for item in publications],
                "circuit_breakers": [item["id"] for item in circuit_breakers],
                "proactive_insights": proactive_insights,
                "ventures_cashflow": venture_cashflow,
                "world": world,
                "executions": executions,
                "execution": execution,
                "company": self.company.status(),
                "portfolio": self.mission.portfolio(),
                "briefing": self.control.daily_briefing(),
                "supervisor": self.supervisor.status(),
            }
            run_status = "partial" if execution.get("status") in {"failed", "review_deferred"} else "completed"
            self.control.store.finish_autonomy_run(run["id"], status=run_status, result=result)
            return result
        except Exception as exc:
            failure = {"status": "failed", "run_id": run["id"], "error": str(exc)}
            self.control.store.finish_autonomy_run(run["id"], status="failed", result=failure)
            raise

    def tick(
        self,
        *,
        now: datetime | None = None,
        max_work_units: int = 1,
        max_new_programmes: int | None = None,
        max_signals: int = 3,
    ) -> dict[str, Any]:
        with self._leader_lock() as leader:
            if leader is False:
                return {
                    "status": "standby",
                    "reason": "another company-autopilot process holds the leader lease",
                    "ventures_cashflow": {"status": "standby"},
                }
            return self._tick_locked(
                now=now, max_work_units=max_work_units,
                max_new_programmes=max_new_programmes, max_signals=max_signals,
            )

    def run_forever(
        self,
        *,
        poll_seconds: float = 30.0,
        max_work_units: int = 1,
        max_new_programmes: int | None = None,
        max_signals: int = 3,
        max_cycles: int | None = None,
        sleep_fn=None,
    ) -> None:
        """Run continuously without crash-looping on deterministic poison work.

        Each failed cycle is already recorded by :meth:`tick`. This outer loop
        adds bounded exponential backoff and a durable circuit breaker. A
        successful cycle clears the failure counter. ``max_cycles`` and
        ``sleep_fn`` exist for deterministic service probes and tests.
        """
        delay = max(5.0, min(float(poll_seconds), 3600.0))
        base_backoff = max(1.0, min(
            float(os.environ.get("AMAURA_AUTOPILOT_FAILURE_BACKOFF_BASE_SECONDS", "5")),
            3600.0,
        ))
        max_backoff = max(base_backoff, min(
            float(os.environ.get("AMAURA_AUTOPILOT_FAILURE_BACKOFF_MAX_SECONDS", "300")),
            86400.0,
        ))
        crash_threshold = max(1, min(
            int(os.environ.get("AMAURA_AUTOPILOT_CRASH_THRESHOLD", "5")), 100
        ))
        sleeper = sleep_fn or time.sleep
        failures = 0
        cycles = 0
        actor = str(getattr(self.supervisor, "worker_id", "amaura-autopilot"))
        while max_cycles is None or cycles < max_cycles:
            cycles += 1
            try:
                self.tick(
                    max_work_units=max_work_units,
                    max_new_programmes=max_new_programmes,
                    max_signals=max_signals,
                )
            except Exception as exc:
                failures += 1
                backoff = min(max_backoff, base_backoff * (2 ** (failures - 1)))
                details = {
                    "consecutive_failures": failures,
                    "threshold": crash_threshold,
                    "backoff_seconds": backoff,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
                self.control.store.set_control(
                    "autopilot.consecutive_failures", str(failures), actor
                )
                self.control.store.publish_event(
                    "company.autopilot.cycle_failed", str(failures), details
                )
                self.control.store.audit(
                    actor, "autopilot_cycle", "runtime", "company", "failed", details
                )
                if failures >= crash_threshold:
                    self.control.store.set_control("autopilot_enabled", "0", actor)
                    self.control.store.set_control(
                        "autopilot.crash_circuit", "open", actor
                    )
                    self.control.store.publish_event(
                        "company.autopilot.circuit_opened", "company", details
                    )
                    self.control.store.audit(
                        actor, "autopilot_crash_circuit", "runtime", "company",
                        "blocked", details,
                    )
                    return
                sleeper(backoff)
                continue
            if failures:
                failures = 0
                self.control.store.set_control(
                    "autopilot.consecutive_failures", "0", actor
                )
                self.control.store.set_control(
                    "autopilot.crash_circuit", "closed", actor
                )
            if max_cycles is None or cycles < max_cycles:
                sleeper(delay)


__all__ = ["AutonomousCompanyRuntime"]
