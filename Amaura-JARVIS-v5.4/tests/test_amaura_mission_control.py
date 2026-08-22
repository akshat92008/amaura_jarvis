from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from jarvis.amaura.autopilot import AutonomousCompanyRuntime
from jarvis.amaura.cognition import IntentEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.mission_control import MissionControl
from jarvis.amaura.models import GovernanceError


def test_punctuated_known_macos_app_is_not_misrouted_as_a_mission() -> None:
    assert IntentEngine().classify("Open Calculator.") == "macos_app"
    assert IntentEngine().classify("Quit Calculator.") == "macos_app"


def _control(monkeypatch, temp: str) -> AmauraControlPlane:
    monkeypatch.setenv("AMAURA_DATA_DIR", temp)
    monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(Path(temp) / "evidence"))
    return AmauraControlPlane(Path(temp) / "amaura.db")


def test_objective_planning_is_persistent_and_idempotent(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            objective = mission.create_objective(
                title="Build owned audience",
                objective="Create the Amaura content package for {cadence_key}",
                success_metric="One package reaches founder approval",
                workflow_key="content_factory",
                cadence="weekly",
                inputs={
                    "campaign_id": "owned-audience",
                    "audience": "AI builders",
                    "business_objective": "Grow owned distribution",
                    "theme": "Amaura week {week}",
                },
                target_value=52,
                unit="packages",
            )
            now = datetime(2026, 8, 5, tzinfo=UTC)
            first = mission.plan_due_work(now=now)
            second = mission.plan_due_work(now=now)
            assert len(first) == 1
            assert second == []
            programme = first[0]["programme"]
            inputs = programme["metadata"]["inputs"]
            assert inputs["objective_id"] == objective["id"]
            assert inputs["cadence_key"] == "2026-W32"
            assert inputs["theme"] == "Amaura week 2026-W32"

            control.close()
            control = AmauraControlPlane(Path(temp) / "amaura.db")
            reloaded = MissionControl(control).portfolio()
            assert reloaded["counts"]["active"] == 1
            assert reloaded["objectives"][0]["programme_count"] == 1
        finally:
            control.close()


def test_active_programme_cap_prevents_runaway_work(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            mission.create_objective(
                title="Weekly product discovery",
                objective="Validate one opportunity for {cadence_key}",
                success_metric="Evidence-backed build or kill decision",
                workflow_key="product_discovery",
                cadence="weekly",
                inputs={"problem_space": "Affordable AI", "target_user": "Students"},
                max_active_programmes=1,
            )
            first = mission.plan_due_work(now=datetime(2026, 8, 5, tzinfo=UTC))
            next_week = mission.plan_due_work(now=datetime(2026, 8, 12, tzinfo=UTC))
            assert len(first) == 1
            assert next_week == []
        finally:
            control.close()


def test_progress_requires_evidence_and_completes_target(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            objective = mission.create_objective(
                title="Validate opportunities",
                objective="Validate product opportunities",
                success_metric="Two decisions recorded",
                workflow_key="product_discovery",
                cadence="manual",
                inputs={"problem_space": "AI", "target_user": "Developers"},
                target_value=2,
                unit="decisions",
            )
            with pytest.raises(GovernanceError, match="evidence"):
                mission.record_progress(objective["id"], delta=1, note="First decision", evidence_refs=[])
            first = mission.record_progress(
                objective["id"],
                delta=1,
                note="First decision",
                evidence_refs=[{"type": "decision", "reference": "artifact://decision/1"}],
            )
            assert first["objective"]["status"] == "active"
            second = mission.record_progress(
                objective["id"],
                delta=1,
                note="Second decision",
                evidence_refs=[{"type": "decision", "reference": "artifact://decision/2"}],
            )
            assert second["objective"]["status"] == "completed"
            assert len(control.store.list_objective_updates(objective["id"])) == 2
        finally:
            control.close()


def test_objective_budget_cannot_underfund_workflow(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            with pytest.raises(GovernanceError, match="below workflow maximum"):
                MissionControl(control).create_objective(
                    title="Underfunded content",
                    objective="Create content",
                    success_metric="Complete",
                    workflow_key="content_factory",
                    inputs={"campaign_id": "underfunded", "audience": "Builders", "business_objective": "Awareness"},
                    budget_cents=1,
                )
        finally:
            control.close()


def test_distribution_bootstrap_is_idempotent(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            first = mission.bootstrap_distribution_first(repository_path=temp)
            second = mission.bootstrap_distribution_first(repository_path=temp)
            assert len(first) == 3
            assert second == []
            assert mission.portfolio()["counts"]["active"] == 3
        finally:
            control.close()


def test_autopilot_kill_switch_stops_planning_and_execution(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            mission.create_objective(
                title="Daily discovery",
                objective="Validate opportunity for {date}",
                success_metric="Decision created",
                workflow_key="product_discovery",
                cadence="daily",
                inputs={"problem_space": "AI", "target_user": "Developers"},
            )
            mission.set_autopilot(False, reason="Founder pause")
            runtime = AutonomousCompanyRuntime(control)
            runtime.supervisor = MagicMock()
            runtime.supervisor.status.return_value = {"ready_tasks": 0}
            result = runtime.tick(now=datetime(2026, 8, 5, tzinfo=UTC))
            assert result["status"] == "paused"
            assert result["objective_programmes_created"] == []
            runtime.supervisor.tick.assert_not_called()
        finally:
            control.close()


def test_autopilot_plans_objective_and_respects_work_unit_limit(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            mission.create_objective(
                title="Daily product discovery",
                objective="Validate opportunity for {date}",
                success_metric="Decision created",
                workflow_key="product_discovery",
                cadence="daily",
                inputs={"problem_space": "AI", "target_user": "Developers"},
            )
            runtime = AutonomousCompanyRuntime(control)
            runtime.supervisor = MagicMock()
            runtime.supervisor.tick.side_effect = [
                {"status": "executed"},
                {"status": "executed"},
                {"status": "idle"},
            ]
            runtime.supervisor.status.return_value = {"ready_tasks": 0}
            result = runtime.tick(now=datetime(2026, 8, 5, tzinfo=UTC), max_work_units=3)
            assert len(result["objective_programmes_created"]) == 1
            assert len(result["executions"]) == 3
        finally:
            control.close()


def test_cadence_claim_is_cross_connection_idempotent(monkeypatch):
    with TemporaryDirectory() as temp:
        first_control = _control(monkeypatch, temp)
        second_control = AmauraControlPlane(Path(temp) / "amaura.db")
        try:
            objective = MissionControl(first_control).create_objective(
                title="Concurrent daily discovery",
                objective="Validate opportunity for {date}",
                success_metric="Decision created",
                workflow_key="product_discovery",
                cadence="daily",
                inputs={"problem_space": "AI", "target_user": "Developers"},
            )
            now = datetime(2026, 8, 5, tzinfo=UTC)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda mission: mission.plan_due_work(now=now),
                        (MissionControl(first_control), MissionControl(second_control)),
                    )
                )
            assert sum(len(result) for result in results) == 1
            programmes = MissionControl(first_control)._programmes_for_objective(objective["id"])
            assert len(programmes) == 1
            run = first_control.store.get_objective_cadence_run(objective["id"], "2026-08-05")
            assert run is not None
            assert run["status"] == "created"
            assert run["programme_id"] == programmes[0]["id"]
        finally:
            first_control.close()
            second_control.close()


def test_daily_autopilot_budget_is_durable(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_AUTOPILOT_DAILY_BUDGET_CENTS", "460")
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            for index, priority in ((1, 1), (2, 2)):
                mission.create_objective(
                    title=f"Daily discovery {index}",
                    objective="Validate opportunity for {date}",
                    success_metric="Decision created",
                    workflow_key="product_discovery",
                    cadence="daily",
                    inputs={"problem_space": f"AI {index}", "target_user": "Developers"},
                    priority=priority,
                )
            now = datetime(2026, 8, 5, tzinfo=UTC)
            first = mission.plan_due_work(now=now, max_new_programmes=2)
            second = mission.plan_due_work(now=now, max_new_programmes=2)
            assert len(first) == 1
            assert second == []
            assert control.store.objective_cadence_budget_for_date("2026-08-05") == 460
        finally:
            control.close()


def test_completed_programme_is_credited_once_with_evidence(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        try:
            mission = MissionControl(control)
            objective = mission.create_objective(
                title="Daily validated decisions",
                objective="Validate opportunity for {date}",
                success_metric="Decision created",
                workflow_key="product_discovery",
                cadence="daily",
                inputs={"problem_space": "AI", "target_user": "Developers"},
                target_value=1,
                unit="decisions",
            )
            now = datetime(2026, 8, 5, tzinfo=UTC)
            programme = mission.plan_due_work(now=now)[0]["programme"]
            control.store.update_work_item(programme["id"], state="completed")

            first = mission.sync_completed_programmes()
            second = mission.sync_completed_programmes()

            assert len(first) == 1
            assert second == []
            updated = control.store.get_objective(objective["id"])
            assert updated["current_value"] == 1
            assert updated["status"] == "completed"
            run = control.store.get_objective_cadence_run(objective["id"], "2026-08-05")
            assert run is not None and run["status"] == "credited"
            updates = control.store.list_objective_updates(objective["id"])
            assert len(updates) == 1
            assert updates[0]["evidence_refs"][0]["type"] == "programme_completion_receipt"
        finally:
            control.close()


def test_autonomous_mission_runs_to_founder_boundary_then_credits_after_approval(monkeypatch):
    from jarvis.amaura.evidence import deterministic_evidence_review
    from jarvis.amaura.supervisor import AmauraSupervisor

    class SuccessfulRunner:
        def __init__(self, control):
            self.control = control

        def run(self, task_id):
            task = self.control.store.get_work_item(task_id)
            submitted = self.control.submit_task(
                task_id,
                actor=task["owner_id"],
                summary="Completed with bounded test evidence.",
                evidence=[
                    {
                        "type": "test_report",
                        "reference": f"artifact://{task_id}/report",
                        "success": True,
                    }
                ],
            )
            return {"status": submitted["state"], "task_id": task_id}

    class SafeReviewer:
        def __init__(self, control):
            self.control = control

        def run(self, task_id):
            task = self.control.store.get_work_item(task_id)
            if task["reviewer_id"] == "founder":
                raise GovernanceError("Founder approval cannot be automated")
            deterministic = deterministic_evidence_review(task, self.control.evidence)
            updated = self.control.review_task(
                task_id,
                actor=task["reviewer_id"],
                approve=True,
                findings="Submitted evidence supports the bounded internal result.",
                attestation={
                    "signature": "test",
                    "decision": {"approve": True, "criteria": []},
                    "deterministic_review": deterministic,
                    "task_id": task_id,
                    "reviewer_id": task["reviewer_id"],
                },
            )
            return {"task_id": task_id, "state": updated["state"]}

    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, temp)
        monkeypatch.setattr("jarvis.amaura.evidence.verify_review_attestation", lambda attestation: True)
        try:
            mission = MissionControl(control)
            objective = mission.create_objective(
                title="Validate one product direction",
                objective="Validate opportunity for {date}",
                success_metric="Founder records one build or kill decision",
                workflow_key="product_discovery",
                cadence="daily",
                inputs={"problem_space": "Affordable AI", "target_user": "Developers"},
                target_value=1,
                unit="decisions",
                priority=1,
            )
            runtime = AutonomousCompanyRuntime(control)
            runtime.ensure_operating_cadence = lambda now=None: []
            runtime.supervisor = AmauraSupervisor(
                control,
                runner_factory=SuccessfulRunner,
                reviewer_factory=SafeReviewer,
                automatic_reviews=True,
            )
            result = runtime.tick(
                now=datetime(2026, 8, 5, tzinfo=UTC),
                max_work_units=20,
                max_new_programmes=1,
            )
            assert result["execution"]["status"] == "idle"
            programme_id = result["objective_programmes_created"][0]
            related = [
                task
                for task in control.list_tasks()
                if (task.get("metadata") or {}).get("inputs", {}).get("objective_id") == objective["id"]
            ]
            assert sum(task["state"] == "completed" for task in related) == 3
            founder_task = next(task for task in related if task["reviewer_id"] == "founder")
            assert founder_task["state"] == "awaiting_approval"
            assert control.store.get_work_item(programme_id)["state"] != "completed"
            assert control.store.get_objective(objective["id"])["current_value"] == 0

            approval = next(
                item for item in control.store.list_approvals("pending") if item["task_id"] == founder_task["id"]
            )
            control.decide_approval(
                approval["id"],
                actor=control.founder_id,
                decision="approved",
                reason="Proceed with the bounded product decision.",
            )
            assert control.store.get_work_item(programme_id)["state"] == "completed"
            credited = mission.sync_completed_programmes()
            assert len(credited) == 1
            final_objective = control.store.get_objective(objective["id"])
            assert final_objective["status"] == "completed"
            assert final_objective["current_value"] == 1
        finally:
            control.close()
