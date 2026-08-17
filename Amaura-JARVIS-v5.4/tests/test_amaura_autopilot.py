from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from jarvis.amaura.autopilot import AutonomousCompanyRuntime
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.mission_runner import MissionRunner
from jarvis.amaura.runtime_lease import company_runtime_leader_lock


def _control(monkeypatch, temp: str) -> AmauraControlPlane:
    monkeypatch.setenv("AMAURA_DATA_DIR", temp)
    monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(Path(temp) / "evidence"))
    return AmauraControlPlane()


def test_autopilot_creates_one_weekly_review_idempotently(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            now = datetime(2026, 8, 5, tzinfo=UTC)
            first = runtime.ensure_operating_cadence(now)
            second = runtime.ensure_operating_cadence(now)
            assert len(first) == 1
            assert second == []
            assert first[0]["programme"]["workflow_id"] == "company_operating_review"
        finally:
            control.close()


def test_autopilot_tick_combines_cadence_missions_execution_and_briefing(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            runtime.supervisor = MagicMock()
            runtime.supervisor.worker_id = "test-runtime"
            runtime.supervisor.tick.return_value = {"status": "idle"}
            runtime.supervisor.status.return_value = {"ready_tasks": 0}
            runtime.mission_runner = MagicMock()
            runtime.mission_runner.tick.return_value = {"status": "idle", "missions": []}

            result = runtime.tick(now=datetime(2026, 8, 5, tzinfo=UTC))

            assert result["status"] == "ok"
            assert result["cadence_programmes_created"]
            assert result["dynamic_missions"] == {"status": "idle", "missions": []}
            runtime.mission_runner.tick.assert_called_once_with(max_goals=3, leader_owned=True)
            assert result["execution"]["status"] == "idle"
            assert "briefing" in result
        finally:
            control.close()


def test_company_runtime_lease_allows_only_one_scheduler(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            with company_runtime_leader_lock(control) as first:
                assert first is True
                with company_runtime_leader_lock(control) as second:
                    assert second is False
        finally:
            control.close()


def test_run_forever_holds_leadership_for_entire_lifetime(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            runtime.tick = MagicMock(side_effect=[{"status": "ok"}, {"status": "ok"}])
            competing_attempts: list[bool] = []

            def sleep_probe(_seconds: float) -> None:
                with company_runtime_leader_lock(control) as competing:
                    competing_attempts.append(competing)

            runtime.run_forever(max_cycles=2, poll_seconds=5, sleep_fn=sleep_probe)

            assert runtime.tick.call_count == 2
            assert competing_attempts == [False]
            assert runtime._leader_owned is False
            with company_runtime_leader_lock(control) as after_shutdown:
                assert after_shutdown is True
        finally:
            control.close()


def test_mission_runner_uses_same_company_runtime_lease(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            runner = MissionRunner(control)
            with company_runtime_leader_lock(control) as leader:
                assert leader is True
                result = runner.tick(max_goals=1)
            assert result["status"] == "standby"
            assert "company runtime" in result["reason"]
        finally:
            control.close()


def test_transient_cycle_failure_backs_off_and_recovers_without_disabling_runtime(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            runtime.tick = MagicMock(
                side_effect=[
                    RuntimeError("temporary provider timeout"),
                    {"status": "ok"},
                ]
            )
            sleeps: list[float] = []
            monkeypatch.setenv("AMAURA_AUTOPILOT_FAILURE_BACKOFF_BASE_SECONDS", "1")
            monkeypatch.setenv("AMAURA_AUTOPILOT_FAILURE_BACKOFF_MAX_SECONDS", "2")
            monkeypatch.setattr("jarvis.amaura.autopilot.random.uniform", lambda _a, _b: 0.0)

            runtime.run_forever(max_cycles=2, poll_seconds=5, sleep_fn=sleeps.append)

            assert runtime.tick.call_count == 2
            assert sleeps == [1.0]
            assert control.store.get_control("autopilot_enabled", "1") == "1"
            assert control.store.get_control("autopilot.consecutive_failures", "0") == "0"
            assert control.store.get_control("autopilot.crash_circuit", "closed") == "closed"
        finally:
            control.close()


def test_integrity_failure_remains_fail_closed(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            runtime.tick = MagicMock(
                side_effect=RuntimeError(
                    "Audit integrity failure: external checkpoint is ahead of the database; possible rollback"
                )
            )
            sleeps: list[float] = []

            with pytest.raises(RuntimeError, match="Audit integrity failure"):
                runtime.run_forever(max_cycles=2, sleep_fn=sleeps.append)

            assert sleeps == []
            assert control.store.get_control("autopilot_enabled", "1") == "1"
        finally:
            control.close()
