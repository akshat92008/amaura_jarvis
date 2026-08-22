from __future__ import annotations

import pytest

from jarvis.amaura.brain import GoalCompiler, GoalRequest
from jarvis.amaura.models import GovernanceError

_REPAIR_OBJECTIVE = (
    "Inspect the current workspace repository. A test is failing. Diagnose the proven root cause, "
    "use the authenticated Antigravity coding path to make the smallest safe repair, independently "
    "verify the result, preserve deterministic evidence of the Antigravity change and review, and "
    "leave the repository with only the necessary source modification. Do not weaken, delete, or alter the test."
)


def _repair_request(tmp_path) -> GoalRequest:
    return GoalRequest(
        objective=_REPAIR_OBJECTIVE,
        workspace=str(tmp_path),
        coding_backend="antigravity",
        autonomy="execute_until_approval",
    )


def test_antigravity_repository_repair_routes_to_repository_write(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "0")
    compiler = GoalCompiler()
    request = _repair_request(tmp_path)

    assert compiler.classify(request) == "software"

    plan = compiler.compile(request)

    assert plan.domain == "software"
    assert plan.planner == "deterministic-software"
    assert plan.coding_backend == "antigravity"
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.action_type == "repository_write"
    assert task.metadata["coding_backend"] == "antigravity"
    assert "Relevant automated tests pass" in task.acceptance_criteria
    assert "No known critical regression remains" in task.acceptance_criteria


def test_repository_repair_fails_closed_if_direct_plan_is_forced(tmp_path):
    compiler = GoalCompiler()
    request = _repair_request(tmp_path)

    with pytest.raises(GovernanceError, match="cannot use direct_action"):
        compiler._direct_action_plan(request, str(tmp_path))


def test_explicit_research_with_cli_workspace_is_not_misrouted_to_repository_work(tmp_path):
    compiler = GoalCompiler()
    request = GoalRequest(
        objective="Research one current AI developer-tool trend and produce an internal recommendation.",
        workspace=str(tmp_path),
        coding_backend="antigravity",
    )

    plan = compiler.compile(request)

    assert plan.domain == "research"
    assert plan.planner == "deterministic-research"
    assert all(task.action_type != "repository_write" for task in plan.tasks)


def test_non_engineering_direct_action_routing_is_preserved(tmp_path):
    compiler = GoalCompiler()
    request = GoalRequest(
        objective="Reply with exactly: ROUTING_OK",
        workspace=str(tmp_path),
        coding_backend="antigravity",
    )

    assert compiler.classify(request) == "direct_action"
