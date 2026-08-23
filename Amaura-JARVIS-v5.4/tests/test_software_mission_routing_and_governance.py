"""Comprehensive regressions for software mission routing, project specification parsing,
model-plan policy validation preflight, safe deterministic fallback, and CLI governance resilience.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.amaura.brain import (
    GoalCompiler,
    GoalRequest,
    JarvisBrain,
    extract_new_project_spec,
)
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError, RiskLevel
from jarvis.amaura.policy import PolicyEngine


def test_extract_new_project_spec():
    """Verify natural project name and destination parsing across common phrasing."""
    # Quoted names with desktop destination
    name, dest = extract_new_project_spec('ok create a supermario game and save it as "sexy" in desktop')
    assert name == "sexy"
    assert dest == "desktop"

    name, dest = extract_new_project_spec('create a supermario game and save it as "sexy" on desktop')
    assert name == "sexy"
    assert dest == "desktop"

    name, dest = extract_new_project_spec('build a new app called "dashboard-v2" on my desktop')
    assert name == "dashboard-v2"
    assert dest == "desktop"

    name, dest = extract_new_project_spec('generate a project named "mario_run" in ~/Projects')
    assert name == "mario_run"
    assert dest == "~/Projects"

    # Unquoted names
    name, dest = extract_new_project_spec("make a python tool called quickcli in desktop")
    assert name == "quickcli"
    assert dest == "desktop"

    name, dest = extract_new_project_spec("create a supermario game and save it as sexy on desktop")
    assert name == "sexy"
    assert dest == "desktop"

    # Fallback semantic slug from nouns
    name, dest = extract_new_project_spec("make a supermario platformer game on desktop")
    assert "supermario" in name or "platformer" in name or "game" in name
    assert dest == "desktop"


def test_existing_repo_phrases_not_new_software_project():
    """Ensure explicit existing-repository maintenance requests are not misrouted as new projects."""
    non_new_requests = [
        "fix this repository",
        "modify the current project",
        "work on this repo",
        "fix bugs in this repo",
        "modify current codebase",
        "debug this repository",
    ]
    for prompt in non_new_requests:
        req = GoalRequest(objective=prompt)
        assert GoalCompiler.is_new_software_project(req) is False, f"Expected False for {prompt}"

    new_requests = [
        'ok create a supermario game and save it as "sexy" in desktop',
        "create a game",
        "build a new app",
        "make a website",
        "generate a new CLI",
        "develop a new project",
    ]
    for prompt in new_requests:
        req = GoalRequest(objective=prompt)
        assert GoalCompiler.is_new_software_project(req) is True, f"Expected True for {prompt}"


def test_real_user_supermario_prompt_routing_and_isolated_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Exact reproduction test for: 'ok create a supermario game and save it as "sexy" in desktop'."""
    projects_root = tmp_path / "DesktopProjects"
    monkeypatch.setenv("AMAURA_PROJECTS_ROOT", str(projects_root))
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "off")

    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        user_prompt = 'ok create a supermario game and save it as "sexy" in desktop'

        req = GoalRequest(
            objective=user_prompt,
            workspace=str(Path.cwd().resolve()),  # Simulate CLI passing current JARVIS repo as launch CWD
            autonomy="plan_only",
        )

        assert GoalCompiler.is_new_software_project(req) is True

        result = brain.submit(req)
        assert result["goal"]["state"] == "draft"

        # Verify the workspace was created at the isolated destination, NOT the launch CWD
        workspace = Path(result["goal"]["metadata"]["workspace"])
        assert workspace == projects_root / "sexy"
        assert workspace != Path.cwd().resolve()
        assert (workspace / ".git").is_dir()
        assert (workspace / "README.md").is_file()

        # Verify task roles and policy validity
        tasks = result["tasks"]
        assert len(tasks) == 2
        impl_task = next(t for t in tasks if t["action_type"] == "repository_write")
        qa_task = next(t for t in tasks if t["action_type"] == "analysis")

        assert impl_task["owner_id"] == "builder"
        assert impl_task["reviewer_id"] == "qa"
        assert impl_task["risk"] == RiskLevel.MEDIUM.value
        assert impl_task["action_type"] == "repository_write"

        assert qa_task["owner_id"] == "qa"
        assert qa_task["reviewer_id"] == "jarvis"
        assert qa_task["risk"] == RiskLevel.LOW.value
        assert qa_task["action_type"] == "analysis"

        # PolicyEngine must strictly validate these assignments
        impl_decision = PolicyEngine.validate_assignment(impl_task)
        assert impl_decision.allowed is True

        qa_decision = PolicyEngine.validate_assignment(qa_task)
        assert qa_decision.allowed is True
    finally:
        control.close()


def test_model_plan_adversarial_qa_medium_risk_preflight_and_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Adversarial test: LLM planner attempts to assign QA to a medium-risk task.

    Preflight must reject it and fall back to the deterministic plan with builder=owner, qa=reviewer.
    """
    projects_root = tmp_path / "projects"
    monkeypatch.setenv("AMAURA_PROJECTS_ROOT", str(projects_root))
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "on")
    monkeypatch.setenv("AMAURA_JARVIS_REQUIRE_LLM_PLANNER", "0")

    def fake_adversarial_planner(request: GoalRequest, prompt: str) -> dict[str, Any]:
        return {
            "domain": "software",
            "objective": request.objective,
            "success_metric": "Adversarial plan",
            "tasks": [
                {
                    "key": "adversarial_task",
                    "title": "Invalid medium-risk task owned by QA",
                    "description": "QA should never own medium-risk work",
                    "owner_id": "qa",
                    "reviewer_id": "technical_architect",
                    "acceptance_criteria": ["Should be rejected"],
                    "depends_on": [],
                    "risk": "medium",
                    "budget_cents": 300,
                    "action_type": "repository_write",
                    "metadata": {},
                }
            ],
        }

    compiler = GoalCompiler(planner=fake_adversarial_planner)
    req = GoalRequest(objective="build a custom reporting service", autonomy="plan_only")

    # compile() should fail validation on the model plan and fall back to deterministic plan
    plan = compiler.compile(req)
    assert plan.planner != "llm"
    assert any(t.owner_id == "builder" for t in plan.tasks)
    # Ensure no medium-risk task is owned by qa
    for t in plan.tasks:
        if t.owner_id == "qa":
            assert t.risk == RiskLevel.LOW


def test_model_plan_adversarial_budget_exceeded_preflight_and_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Adversarial test: LLM planner attempts to exceed employee budget cost limit."""
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "on")
    monkeypatch.setenv("AMAURA_JARVIS_REQUIRE_LLM_PLANNER", "0")

    def fake_budget_exceeded_planner(request: GoalRequest, prompt: str) -> dict[str, Any]:
        return {
            "domain": "software",
            "objective": request.objective,
            "success_metric": "Over-budget plan",
            "tasks": [
                {
                    "key": "expensive_task",
                    "title": "Task exceeding builder limit",
                    "description": "Cost exceeds cost_limit_cents",
                    "owner_id": "builder",
                    "reviewer_id": "qa",
                    "acceptance_criteria": ["Over budget"],
                    "depends_on": [],
                    "risk": "medium",
                    "budget_cents": 99999,  # builder cost limit is 1200
                    "action_type": "repository_write",
                    "metadata": {},
                }
            ],
        }

    compiler = GoalCompiler(planner=fake_budget_exceeded_planner)
    req = GoalRequest(objective="build a game", autonomy="plan_only")

    plan = compiler.compile(req)
    # Plan must have fallen back to safe deterministic plan
    for t in plan.tasks:
        if t.owner_id == "builder":
            assert t.budget_cents <= 1200


def test_model_plan_required_fails_closed_no_db_pollution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When LLM planner is required (AMAURA_JARVIS_REQUIRE_LLM_PLANNER=1) and produces an invalid plan,

    fail-closed must raise GovernanceError and persist 0 partial mission records in the database.
    """
    monkeypatch.setenv("AMAURA_JARVIS_REQUIRE_LLM_PLANNER", "1")

    def fake_invalid_planner(request: GoalRequest, prompt: str) -> dict[str, Any]:
        return {
            "domain": "software",
            "objective": request.objective,
            "success_metric": "Invalid plan",
            "tasks": [
                {
                    "key": "invalid_task",
                    "title": "Invalid assignment",
                    "description": "QA owning medium risk",
                    "owner_id": "qa",
                    "reviewer_id": "technical_architect",
                    "acceptance_criteria": ["None"],
                    "depends_on": [],
                    "risk": "medium",
                    "budget_cents": 500,
                    "action_type": "repository_write",
                    "metadata": {},
                }
            ],
        }

    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        compiler = GoalCompiler(planner=fake_invalid_planner)
        brain = JarvisBrain(control, compiler=compiler)

        req = GoalRequest(objective="create a service", autonomy="plan_only")
        with pytest.raises(GovernanceError) as exc_info:
            brain.submit(req)

        assert "may not own medium-risk work" in str(exc_info.value)

        # Verify atomic guarantee: ZERO work items exist in the store
        items = control.store.list_work_items(limit=100)
        assert len(items) == 0, f"Expected 0 work items in DB, found: {items}"
    finally:
        control.close()


def test_cognition_and_cli_governance_error_resilience(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that a GovernanceError is gracefully caught at cognition/kernel level and does not kill the process."""
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        kernel = ExecutiveKernel(control)

        # 1. First turn: A request that triggers governed execution
        res1 = kernel.handle(
            ExecutiveRequest(
                text="create a supermario game",
                autonomy="execute_until_approval",
                coding_backend="antigravity",
            )
        )
        assert res1.state in {"completed", "queued", "created", "draft"} or "⚠" in res1.message

        # 2. Next turn: "what is 12 * 12?" continues to work cleanly
        res2 = kernel.handle(ExecutiveRequest(text="what is 12 * 12?"))
        assert "144" in res2.message
    finally:
        control.close()


def test_independent_verification_failure_is_not_retryable(tmp_path: Path):
    """Prove that a test-assertion failure from independent verification does NOT
    re-run the Antigravity coding worker.

    Requirement: WORKER_EXECUTIONS == 1 even when verification raises IndependentVerificationError.
    The task must be marked FAILED (not blocked/assigned) so the supervisor does not
    schedule a second full Antigravity build.
    """
    from unittest.mock import patch

    from jarvis.amaura.executor import GovernedTaskRunner
    from jarvis.amaura.models import IndependentVerificationError, TaskState

    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        worker_call_count = 0
        _verification_error = IndependentVerificationError(
            "Command failed independent verification: 'python3 -m unittest discover -s tests -v': "
            "AssertionError: 'STAGE_CLEAR' != 'VICTORY'"
        )

        def fake_antigravity_delivery(self_ref, task_id, task, packet_dict):
            nonlocal worker_call_count
            worker_call_count += 1
            raise _verification_error

        executor = GovernedTaskRunner(control)

        # Insert a minimal software task directly into the store
        task_id = "task_verif_regression_001"
        control.store.insert_work_item(
            {
                "id": task_id,
                "item_type": "task",
                "workflow_id": "software_delivery",
                "step_key": "build",
                "owner_id": "builder",
                "reviewer_id": "qa",
                "state": TaskState.ASSIGNED.value,
                "priority": 2,
                "risk": "medium",
                "action_type": "repository_write",
                "title": "Test verification non-retry",
                "description": "Write a Mario game",
                "success_metric": "game files exist and tests pass",
                "budget_cents": 1200,
                "metadata": {
                    "coding_backend": "antigravity",
                    "workspace": str(tmp_path),
                    "dynamic_goal": True,
                },
            }
        )

        with (
            patch("jarvis.amaura.antigravity_bridge.AntigravityDeliveryAdapter.configured", True),
            patch.object(GovernedTaskRunner, "_run_antigravity_delivery", fake_antigravity_delivery),
        ):
            result = executor.run(task_id)

        # Worker was called exactly once — not retried
        assert worker_call_count == 1, f"Worker must execute exactly once; got {worker_call_count}"

        # Task must be FAILED (not blocked/assigned) so the supervisor cannot retry
        final_task = control.store.get_work_item(task_id)
        assert final_task["state"] == TaskState.FAILED.value, (
            f"Verification failure must leave task in FAILED state, got: {final_task['state']}"
        )

        # Result must be non-retryable
        assert result.get("retryable") is False, "Verification failure result must be non-retryable"
        assert "Command failed independent verification" in result.get("reason", "")

        # Verify no active or leaked execution leases remain
        exec_status = control.store.execution_status()
        assert len(exec_status["active"]) == 0, f"Expected 0 active leases, found: {exec_status['active']}"

        # Subsequent execution attempt does NOT invoke the worker again because task is FAILED
        with (
            patch("jarvis.amaura.antigravity_bridge.AntigravityDeliveryAdapter.configured", True),
            patch.object(GovernedTaskRunner, "_run_antigravity_delivery", fake_antigravity_delivery),
        ):
            try:
                executor.run(task_id)
            except Exception:
                pass
        assert worker_call_count == 1, "Failed task must not re-execute worker on subsequent run call"
    finally:
        control.close()


def test_genuine_transient_failure_preserves_retryable_behavior(tmp_path: Path):
    """Prove that genuine transient/infrastructure failures (e.g. TimeoutError or
    temporary provider error) preserve existing recoverable retry behavior (retryable=True).
    """
    from unittest.mock import patch

    from jarvis.amaura.executor import GovernedTaskRunner
    from jarvis.amaura.models import TaskState

    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        worker_call_count = 0

        def fake_transient_failure(self_ref, task_id, task, packet_dict):
            nonlocal worker_call_count
            worker_call_count += 1
            raise TimeoutError("Temporary provider connection timeout")

        executor = GovernedTaskRunner(control)

        task_id = "task_transient_regression_002"
        control.store.insert_work_item(
            {
                "id": task_id,
                "item_type": "task",
                "workflow_id": "software_delivery",
                "step_key": "build",
                "owner_id": "builder",
                "reviewer_id": "qa",
                "state": TaskState.ASSIGNED.value,
                "priority": 2,
                "risk": "medium",
                "action_type": "repository_write",
                "title": "Test transient retryable",
                "description": "Write a utility tool",
                "success_metric": "tests pass",
                "budget_cents": 1200,
                "metadata": {
                    "coding_backend": "antigravity",
                    "workspace": str(tmp_path),
                    "dynamic_goal": True,
                },
            }
        )

        with (
            patch("jarvis.amaura.antigravity_bridge.AntigravityDeliveryAdapter.configured", True),
            patch.object(GovernedTaskRunner, "_run_antigravity_delivery", fake_transient_failure),
        ):
            result = executor.run(task_id)

        assert worker_call_count == 1
        final_task = control.store.get_work_item(task_id)
        # Transient failure leaves task BLOCKED with retryable=True
        assert final_task["state"] == TaskState.BLOCKED.value
        assert result.get("retryable") is True
        assert result.get("status") == "blocked"
    finally:
        control.close()
