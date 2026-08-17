"""Canonical autonomous company runtime for Amaura Labs.

The runtime never broadens authority. It advances only governed internal work,
keeps external publication/messaging/deployment/spending behind the existing
approval policies, and coordinates dynamic founder missions under one canonical
company-level leadership lease.
"""

from __future__ import annotations

import os
import random
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.amaura.cognition import ProactiveCognition, WorldModel
from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.founder_attention import FounderAttentionEngine
from jarvis.amaura.mission_control import MissionControl
from jarvis.amaura.mission_runner import MissionRunner
from jarvis.amaura.runtime_lease import company_runtime_leader_lock
from jarvis.amaura.signal_ingestion import SignalIngestionEngine
from jarvis.amaura.supervisor import AmauraSupervisor


class AutonomousCompanyRuntime:
    """Single canonical long-running company scheduler."""

    _FAIL_CLOSED_TERMS = (
        "audit integrity failure",
        "checkpoint is ahead",
        "evidence integrity",
        "tamper",
        "approval signature",
        "approval integrity",
        "sandbox escape",
        "outside workspace",
        "security policy",
    )

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
        self.mission_runner = MissionRunner(control)
        self.company = CompanyAutonomyEngine(control, worker_id=worker_id)
        self.signal_ingestion = SignalIngestionEngine(control, company=self.company)
        self.world = WorldModel(control)
        self.proactive = ProactiveCognition(control, world=self.world)
        self.attention = FounderAttentionEngine(control, world=self.world)

    @contextmanager
    def _leader_lock(self):
        """Acquire the one authoritative company-runtime scheduling lease."""
        with company_runtime_leader_lock(self.control) as leader:
            yield leader

    @staticmethod
    def _week_key(now: datetime) -> str:
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"

    @staticmethod
    def _proactive_enabled() -> bool:
        # CompanyAutonomy already converts known operational pressure into
        # bounded workflows. Broad autonomous investigation is opt-in until the
        # strategic-radar layer can prove it will not duplicate those workflows.
        return os.environ.get("AMAURA_V7_AUTO_INVESTIGATE", "0").strip().lower() not in {
            "0",
            "false",
            "off",
            "disabled",
        }

    @classmethod
    def _must_fail_closed(cls, exc: BaseException) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(term in text for term in cls._FAIL_CLOSED_TERMS)

    def ensure_operating_cadence(self, now: datetime | None = None) -> list[dict[str, Any]]:
        if self.control.store.get_control("autopilot_enabled", "1") != "1":
            return []
        now = now or datetime.now(UTC)
        week_key = self._week_key(now)
        if any(
            objective.get("workflow_key") == "company_operating_review" and objective.get("status") == "active"
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
        """Create and verify one durable backup per UTC day."""
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
                    f"Automatic backup verification failed: integrity={integrity!r}, foreign_keys={len(foreign_keys)}"
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
        max_dynamic_goals: int = 3,
    ) -> dict[str, Any]:
        """Run one deterministic company cycle while leadership is already held.

        Canonical order:
        recover/sync -> external observations -> internal signals -> signal
        workflows -> world/proactive cognition -> recurring objectives -> dynamic
        missions -> governed execution/outbox -> circuits -> final world/attention
        -> venture accounting -> briefing/backup.
        """
        now = now or datetime.now(UTC)
        run = self.control.store.start_autonomy_run(
            worker_id=str(getattr(self.supervisor, "worker_id", "amaura-autopilot")),
            mode="company_tick",
        )
        backup = self.ensure_daily_backup(now)
        enabled = self.control.store.get_control("autopilot_enabled", "1") == "1"
        if not enabled:
            world = self.world.refresh()
            result = {
                "status": "paused",
                "run_id": run["id"],
                "backup": backup,
                "external_signal_ingestion": {"status": "paused"},
                "cadence_programmes_created": [],
                "objective_programmes_created": [],
                "signals_detected": [],
                "signal_programmes_created": [],
                "objective_progress_updates": [],
                "dynamic_missions": {"status": "paused", "missions": []},
                "publications_enqueued": [],
                "circuit_breakers": [],
                "proactive_insights": self.proactive.scan(snapshot=world),
                "proactive_investigations": [],
                "world": world,
                "founder_attention": self.attention.summary(snapshot=world),
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

            external_signal_ingestion = self.signal_ingestion.poll()
            signals_detected = self.company.detect_signals(now=now)
            signal_programmes = self.company.process_signals(now=now, max_signals=max_signals)

            self.world.refresh()
            proactive_cycle = self.proactive.tick(auto_investigate=self._proactive_enabled())

            created = self.ensure_operating_cadence(now)
            objective_programmes = self.mission.plan_due_work(now=now, max_new_programmes=max_new_programmes)

            dynamic_missions = self.mission_runner.tick(
                max_goals=max(1, min(int(max_dynamic_goals), 20)),
                leader_owned=True,
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
            world = self.world.refresh()
            attention = self.attention.summary(snapshot=world)

            from jarvis.amaura.ventures_cashflow import CashflowEngine

            venture_cashflow = CashflowEngine(self.control).tick(
                actor="jarvis",
                proposal_limit=max(1, min(int(os.environ.get("AMAURA_VENTURE_PROPOSALS_PER_CYCLE", "4")), 20)),
            )
            result = {
                "status": "ok",
                "run_id": run["id"],
                "backup": backup,
                "external_signal_ingestion": external_signal_ingestion,
                "cadence_programmes_created": [item["programme"]["id"] for item in created],
                "objective_programmes_created": [item["programme"]["id"] for item in objective_programmes],
                "signals_detected": [item["id"] for item in signals_detected],
                "signal_programmes_created": [item["programme"]["programme"]["id"] for item in signal_programmes],
                "objective_progress_updates": progress_updates,
                "dynamic_missions": dynamic_missions,
                "publications_enqueued": [item["id"] for item in publications],
                "circuit_breakers": [item["id"] for item in circuit_breakers],
                "proactive_insights": proactive_cycle["insights"],
                "proactive_investigations": proactive_cycle["investigations"],
                "ventures_cashflow": venture_cashflow,
                "world": world,
                "founder_attention": attention,
                "executions": executions,
                "execution": execution,
                "company": self.company.status(),
                "portfolio": self.mission.portfolio(),
                "briefing": self.control.daily_briefing(),
                "supervisor": self.supervisor.status(),
            }
            partial_states = {"failed", "review_deferred"}
            mission_states = {str(item.get("state") or "") for item in dynamic_missions.get("missions", [])}
            run_status = "partial" if execution.get("status") in partial_states or mission_states & partial_states else "completed"
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
        max_dynamic_goals: int = 3,
    ) -> dict[str, Any]:
        with self._leader_lock() as leader:
            if leader is False:
                return {
                    "status": "standby",
                    "reason": "another company runtime process holds the leader lease",
                    "ventures_cashflow": {"status": "standby"},
                }
            return self._tick_locked(
                now=now,
                max_work_units=max_work_units,
                max_new_programmes=max_new_programmes,
                max_signals=max_signals,
                max_dynamic_goals=max_dynamic_goals,
            )

    def run_forever(
        self,
        *,
        poll_seconds: float = 30.0,
        max_work_units: int = 1,
        max_new_programmes: int | None = None,
        max_signals: int = 3,
        max_dynamic_goals: int = 3,
        max_cycles: int | None = None,
        sleep_fn=None,
    ) -> None:
        delay = max(5.0, min(float(poll_seconds), 3600.0))
        base_backoff = max(
            1.0,
            min(float(os.environ.get("AMAURA_AUTOPILOT_FAILURE_BACKOFF_BASE_SECONDS", "5")), 3600.0),
        )
        max_backoff = max(
            base_backoff,
            min(float(os.environ.get("AMAURA_AUTOPILOT_FAILURE_BACKOFF_MAX_SECONDS", "300")), 86400.0),
        )
        crash_threshold = max(1, min(int(os.environ.get("AMAURA_AUTOPILOT_CRASH_THRESHOLD", "5")), 100))
        sleeper = sleep_fn or time.sleep
        failures = 0
        cycles = 0
        actor = str(getattr(self.supervisor, "worker_id", "amaura-autopilot"))

        while max_cycles is None or cycles < max_cycles:
            cycles += 1
            try:
                result = self.tick(
                    max_work_units=max_work_units,
                    max_new_programmes=max_new_programmes,
                    max_signals=max_signals,
                    max_dynamic_goals=max_dynamic_goals,
                )
            except Exception as exc:
                if self._must_fail_closed(exc):
                    details = {
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                        "fail_closed": True,
                    }
                    self.control.store.publish_event("company.autopilot.integrity_blocked", "company", details)
                    self.control.store.audit(actor, "autopilot_cycle", "runtime", "company", "blocked", details)
                    raise

                failures += 1
                raw_backoff = min(max_backoff, base_backoff * (2 ** (failures - 1)))
                jitter = random.uniform(0.0, min(base_backoff, raw_backoff * 0.25))
                backoff = min(max_backoff, raw_backoff + jitter)
                details = {
                    "consecutive_failures": failures,
                    "threshold": crash_threshold,
                    "backoff_seconds": backoff,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
                self.control.store.set_control("autopilot.consecutive_failures", str(failures), actor)
                self.control.store.publish_event("company.autopilot.cycle_failed", str(failures), details)
                self.control.store.audit(actor, "autopilot_cycle", "runtime", "company", "failed", details)
                if failures == crash_threshold:
                    self.control.store.set_control("autopilot.crash_circuit", "open", actor)
                    self.control.store.publish_event("company.autopilot.circuit_opened", "company", details)
                    self.control.store.audit(
                        actor,
                        "autopilot_crash_circuit",
                        "runtime",
                        "company",
                        "degraded",
                        details,
                    )
                sleeper(backoff)
                continue

            if result.get("status") == "standby":
                if max_cycles is None or cycles < max_cycles:
                    sleeper(delay)
                continue

            if failures:
                failures = 0
                self.control.store.set_control("autopilot.consecutive_failures", "0", actor)
                self.control.store.set_control("autopilot.crash_circuit", "closed", actor)
            if max_cycles is None or cycles < max_cycles:
                sleeper(delay)


__all__ = ["AutonomousCompanyRuntime"]