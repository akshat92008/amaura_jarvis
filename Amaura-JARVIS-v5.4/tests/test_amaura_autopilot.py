from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from jarvis.amaura.autopilot import AutonomousCompanyRuntime
from jarvis.amaura.control_plane import AmauraControlPlane


def test_autopilot_creates_one_weekly_review_idempotently(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_DATA_DIR", temp)
        monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(Path(temp) / "evidence"))
        control = AmauraControlPlane()
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


def test_autopilot_tick_combines_cadence_execution_and_briefing(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_DATA_DIR", temp)
        monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(Path(temp) / "evidence"))
        control = AmauraControlPlane()
        try:
            runtime = AutonomousCompanyRuntime(control)
            runtime.supervisor = MagicMock()
            runtime.supervisor.tick.return_value = {"status": "idle"}
            runtime.supervisor.status.return_value = {"ready_tasks": 0}
            result = runtime.tick(now=datetime(2026, 8, 5, tzinfo=UTC))
            assert result["status"] == "ok"
            assert result["cadence_programmes_created"]
            assert result["execution"]["status"] == "idle"
            assert "briefing" in result
        finally:
            control.close()
