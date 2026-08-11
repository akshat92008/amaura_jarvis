from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from jarvis.amaura.autopilot import AutonomousCompanyRuntime
from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.mission_control import MissionControl
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.workflows import WORKFLOWS


def _control(monkeypatch, temp: str) -> AmauraControlPlane:
    monkeypatch.setenv("AMAURA_DATA_DIR", temp)
    monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(Path(temp) / "evidence"))
    return AmauraControlPlane(Path(temp) / "amaura.db")


def test_full_company_bootstrap_is_idempotent(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            first = engine.bootstrap_company(repository_path=temp)
            second = engine.bootstrap_company(repository_path=temp)
            assert len(first["created"]) == 15
            assert second["created"] == []
            assert len(second["existing"]) == 15
            workflows = {item["workflow_key"] for item in first["created"]}
            assert {
                "research_intelligence_cycle",
                "product_discovery",
                "engineering_reliability_cycle",
                "content_factory",
                "distribution_optimization_cycle",
                "customer_feedback_cycle",
                "community_growth_cycle",
                "product_revenue_cycle",
                "financial_control_cycle",
                "security_watch_cycle",
                "open_source_release_cycle",
                "company_operating_review",
                "venture_opportunity_cycle",
                "venture_cashflow_cycle",
                "venture_portfolio_review",
            } == workflows
            assert engine.status()["bootstrapped"] is True
        finally:
            control.close()


def test_every_autonomy_workflow_exists_and_has_independent_reviewers():
    required = {
        "research_intelligence_cycle",
        "engineering_reliability_cycle",
        "distribution_optimization_cycle",
        "customer_feedback_cycle",
        "community_growth_cycle",
        "financial_control_cycle",
        "open_source_release_cycle",
        "product_revenue_cycle",
        "security_watch_cycle",
    }
    assert required.issubset(WORKFLOWS)
    for workflow_key in required:
        workflow = WORKFLOWS[workflow_key]
        assert workflow.steps
        for step in workflow.steps:
            assert step.owner_id != step.reviewer_id
            assert step.acceptance_criteria


def test_signal_ingestion_is_idempotent_and_creates_one_programme(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control, worker_id="signal-worker")
            engine.bootstrap_company(repository_path=temp)
            signal_a = engine.ingest_signal(
                signal_type="build_failure",
                source="ci",
                severity="high",
                payload={"repository_path": temp, "summary": "tests failed"},
                idempotency_key="ci:run:42",
                actor=control.founder_id,
            )
            signal_b = engine.ingest_signal(
                signal_type="build_failure",
                source="ci",
                severity="high",
                payload={"repository_path": temp, "summary": "tests failed"},
                idempotency_key="ci:run:42",
                actor=control.founder_id,
            )
            assert signal_a["id"] == signal_b["id"]
            results = engine.process_signals(now=datetime(2026, 8, 5, tzinfo=UTC))
            assert len(results) == 1
            assert results[0]["programme"]["programme"]["workflow_id"] == "engineering_reliability_cycle"
            assert engine.process_signals(now=datetime(2026, 8, 5, tzinfo=UTC)) == []
            stored = control.store.get_company_signal(signal_a["id"])
            assert stored["status"] == "resolved"
            assert stored["programme_id"]
        finally:
            control.close()


def test_signal_claim_is_exactly_once_across_connections(monkeypatch):
    with TemporaryDirectory() as temp:
        first = _control(monkeypatch, temp)
        second = AmauraControlPlane(Path(temp) / "amaura.db")
        try:
            CompanyAutonomyEngine(first).ingest_signal(
                signal_type="customer_feedback",
                source="support",
                severity="medium",
                payload={"product_name": "Nexus", "summary": "onboarding confusion"},
                idempotency_key="feedback:1",
                actor=first.founder_id,
            )

            def claim(control: AmauraControlPlane, worker: str):
                return control.store.claim_company_signals(worker_id=worker, limit=1)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda pair: claim(*pair), [(first, "a"), (second, "b")]))
            assert sum(len(items) for items in results) == 1
        finally:
            first.close()
            second.close()


def test_signal_budget_cap_prevents_runaway_work(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_SIGNAL_DAILY_BUDGET_CENTS", "500")
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            engine.bootstrap_company(repository_path=temp)
            engine.ingest_signal(
                signal_type="build_failure",
                source="ci",
                severity="high",
                payload={"repository_path": temp, "summary": "failure"},
                idempotency_key="budget:1",
                actor=control.founder_id,
            )
            assert engine.process_signals(now=datetime(2026, 8, 5, tzinfo=UTC)) == []
            pending = control.store.list_company_signals(status="pending")
            assert len(pending) == 1
            assert "budget" in pending[0]["error"]
        finally:
            control.close()


def test_paused_department_blocks_objective_and_signal_planning(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            bootstrap = engine.bootstrap_company(repository_path=temp)
            engine.set_department(
                "growth_media", enabled=False, reason="quality investigation"
            )
            now = datetime(2026, 8, 5, tzinfo=UTC)
            planned = MissionControl(control).plan_due_work(now=now, max_new_programmes=20)
            assert all(item["programme"]["workflow_id"] not in {"content_factory", "distribution_optimization_cycle"} for item in planned)
            engine.ingest_signal(
                signal_type="content_underperformance",
                source="analytics",
                severity="medium",
                payload={"channel": "youtube", "audience": "developers"},
                actor=control.founder_id,
            )
            assert engine.process_signals(now=now) == []
            assert control.store.list_company_signals(status="pending")
            assert bootstrap["portfolio"]["counts"]["active"] == 15
        finally:
            control.close()


def test_failure_circuit_breaker_pauses_department(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_DEPARTMENT_FAILURE_THRESHOLD", "3")
        control = _control(monkeypatch, temp)
        try:
            programme = control.create_program(
                objective="repair repository",
                success_metric="verified",
                workflow_key="engineering_reliability_cycle",
                inputs={"repository_path": temp},
            )
            for task in programme["tasks"][:3]:
                control.store.update_work_item(task["id"], state="failed")
            engine = CompanyAutonomyEngine(control)
            alerts = engine.evaluate_circuit_breakers(now=datetime.now(UTC))
            assert len(alerts) == 1
            assert engine.department_paused("product_engineering") is True
            assert alerts[0]["code"] == "department_circuit_breaker"
        finally:
            control.close()


def test_autopilot_records_run_and_processes_signal(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            engine.bootstrap_company(repository_path=temp)
            engine.ingest_signal(
                signal_type="runway_risk",
                source="finance",
                severity="high",
                payload={"summary": "subscription cost spike"},
                actor=control.founder_id,
            )
            runtime = AutonomousCompanyRuntime(control)
            runtime.supervisor = MagicMock()
            runtime.supervisor.worker_id = "test-autopilot"
            runtime.supervisor.tick.return_value = {"status": "idle"}
            runtime.supervisor.status.return_value = {"ready_tasks": 0}
            result = runtime.tick(
                now=datetime(2026, 8, 5, tzinfo=UTC),
                max_work_units=1,
                max_new_programmes=1,
                max_signals=1,
            )
            assert result["status"] == "ok"
            assert len(result["signal_programmes_created"]) == 1
            runs = control.store.list_autonomy_runs(limit=5)
            assert runs[0]["status"] == "completed"
            assert runs[0]["result"]["run_id"] == result["run_id"]
        finally:
            control.close()


def test_invalid_signal_and_non_founder_department_change_are_rejected(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            with pytest.raises(GovernanceError, match="Unsupported"):
                engine.ingest_signal(
                    signal_type="unknown",
                    source="test",
                    severity="low",
                    payload={"x": 1},
                    actor=control.founder_id,
                )
            with pytest.raises(GovernanceError, match="founder"):
                engine.set_department(
                    "finance", enabled=False, reason="test", actor="jarvis"
                )
        finally:
            control.close()


def test_self_observation_detects_alert_failed_task_and_weak_content(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            engine.bootstrap_company(repository_path=temp)
            control.store.create_alert(
                {
                    "id": "alert_manual_1",
                    "severity": "critical",
                    "code": "provider_ambiguity",
                    "message": "Provider completion is ambiguous",
                    "resource_id": "outbox_1",
                    "details": {"provider": "youtube"},
                }
            )
            programme = control.create_program(
                objective="verify build",
                success_metric="verified",
                workflow_key="engineering_reliability_cycle",
                inputs={"repository_path": temp},
            )
            control.store.update_work_item(
                programme["tasks"][0]["id"], state="failed", summary="compile failed"
            )
            control.content_factory.create_campaign(
                campaign_id="weak-content",
                title="Weak content",
                audience="developers",
                business_objective="distribution",
                config={},
            )
            control.content_factory.record_metrics(
                "weak-content",
                platform="youtube",
                window="72h",
                metrics={"ctr": 0.01, "retention": 0.20},
            )
            detected = engine.detect_signals(now=datetime.now(UTC))
            detected_types = {item["signal_type"] for item in detected}
            assert {
                "security_incident",
                "build_failure",
                "content_underperformance",
            }.issubset(detected_types)
            assert engine.detect_signals(now=datetime.now(UTC)) == []
        finally:
            control.close()


def test_self_observation_detects_monthly_cost_pressure(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_MONTHLY_COST_ALERT_CENTS", "50")
        control = _control(monkeypatch, temp)
        try:
            engine = CompanyAutonomyEngine(control)
            programme = control.create_program(
                objective="research",
                success_metric="done",
                workflow_key="research_intelligence_cycle",
                inputs={"research_theme": "efficient models"},
            )
            task = programme["tasks"][0]
            control.record_cost(
                task["id"], task["owner_id"], 50, "model_api", units=1000, unit_name="tokens"
            )
            detected = engine.detect_signals(now=datetime.now(UTC))
            assert any(item["signal_type"] == "runway_risk" for item in detected)
        finally:
            control.close()


def test_autopilot_creates_verified_daily_backup_once(monkeypatch):
    with TemporaryDirectory() as temp:
        backup_dir = Path(temp) / "backups"
        monkeypatch.setenv("AMAURA_BACKUP_DIR", str(backup_dir))
        monkeypatch.setenv("AMAURA_AUTOMATIC_BACKUPS", "1")
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
            first = runtime.ensure_daily_backup(now)
            second = runtime.ensure_daily_backup(now)
            assert first["status"] == "created"
            assert first["integrity"] == ["ok"]
            assert first["foreign_key_violations"] == 0
            assert Path(first["path"]).exists()
            assert second["status"] == "current"
            assert second["path"] == first["path"]
        finally:
            control.close()


def test_autopilot_backup_can_be_disabled(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_AUTOMATIC_BACKUPS", "0")
        control = _control(monkeypatch, temp)
        try:
            runtime = AutonomousCompanyRuntime(control)
            assert runtime.ensure_daily_backup(datetime(2026, 8, 5, tzinfo=UTC)) == {
                "status": "disabled"
            }
        finally:
            control.close()
