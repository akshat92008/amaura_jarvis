from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from jarvis.amaura.brain import GoalCompiler, GoalRequest, JarvisBrain
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.nexus_bridge import NexusDeliveryAdapter
from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Amaura Test"], cwd=path, check=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def test_goal_compiler_creates_dynamic_software_dag(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    request = GoalRequest(objective="Build a tested API feature", workspace=str(repo), autonomy="plan_only")
    plan = GoalCompiler().compile(request)
    assert plan.domain == "software"
    assert [task.key for task in plan.tasks] == [
        "requirements", "repo_inspection", "technical_plan", "implementation", "verification"
    ]
    assert plan.tasks[3].action_type == "repository_write"
    assert plan.tasks[3].depends_on == ["technical_plan"]
    assert plan.tasks[4].depends_on == ["implementation"]


def test_goal_compiler_recognises_new_game_as_software(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "off")
    request = GoalRequest(objective="Create a platform game on my desktop", autonomy="execute")
    plan = GoalCompiler().compile(request)
    assert plan.domain == "software"
    assert [task.key for task in plan.tasks] == ["implementation", "verification"]
    assert plan.tasks[0].action_type == "repository_write"
    assert plan.tasks[0].depends_on == []
    assert plan.tasks[1].depends_on == ["implementation"]
    assert GoalCompiler.is_new_software_project(request) is True


def test_new_software_project_gets_isolated_managed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects = tmp_path / "projects"
    monkeypatch.setenv("AMAURA_PROJECTS_ROOT", str(projects))
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "off")
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        result = JarvisBrain(control).submit(
            GoalRequest(objective="Create a platformer game", autonomy="plan_only")
        )
        workspace = Path(result["goal"]["metadata"]["workspace"])
        assert workspace.parent == projects
        assert (workspace / ".git").is_dir()
        assert (workspace / "README.md").is_file()
        assert result["plan"]["domain"] == "software"
        implementation = next(task for task in result["tasks"] if task["action_type"] == "repository_write")
        assert implementation["metadata"]["workspace"] == str(workspace)
    finally:
        control.close()


def test_jarvis_memory_and_plan_only_goal_are_durable(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        saved = brain.memory.remember(key="preferred_stack", value={"frontend": "Next.js"}, scope="project")
        assert saved["value"] == {"frontend": "Next.js"}
        assert "Next.js" in brain.memory.context("frontend stack")

        result = brain.submit(GoalRequest(objective="Research a launch checklist", autonomy="plan_only"))
        assert result["execution"] is None
        assert result["goal"]["metadata"]["dynamic_goal"] is True
        status = brain.status(result["goal"]["id"])
        assert status["state"] == "queued"
        assert status["tasks"]
    finally:
        control.close()


def test_antigravity_backend_is_handoff_not_fake_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    handoff_dir = tmp_path / "handoffs"
    monkeypatch.setenv("AMAURA_HANDOFF_DIR", str(handoff_dir))
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_MODE", "handoff")
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        result = JarvisBrain(control).submit(
            GoalRequest(
                objective="Implement a safe dashboard feature",
                workspace=str(repo),
                coding_backend="antigravity",
                autonomy="execute",
            )
        )
        assert result["execution"] is None
        assert result["requires_founder_action"] is True
        assert result["handoff"]["provider"] == "antigravity"
        assert Path(result["handoff"]["json_path"]).is_file()
    finally:
        control.close()


def _fake_noryx(path: Path) -> Path:
    script = path / "fake_noryx.py"
    script.write_text(
        '''#!/usr/bin/env python3\nimport argparse, json, os, pathlib\np=argparse.ArgumentParser(); p.add_argument("command"); p.add_argument("--request-file"); p.add_argument("--result-file"); a=p.parse_args()\nreq=json.load(open(a.request_file))\nassert req["schema"] == "amaura.noryx-task.v1"\nassert req["requirements"]["result_schema"] == "amaura.noryx-result.v2"\nassert "AMAURA_OPERATOR_KEY" not in os.environ\nrepo=pathlib.Path(req["repository_path"]); target=repo/"noryx_fix.py"; target.write_text("VALUE=1\\n")\njson.dump({"schema":"amaura.noryx-result.v2","success":True,"summary":"Implemented and verified the requested change","run_id":"run-123","changed_files":["noryx_fix.py"],"tests":[{"command":"python -m py_compile noryx_fix.py","exit_code":0,"passed":True,"summary":"fixture verification"}],"evidence":[{"type":"test","reference":"fixture:test","summary":"fixture evidence"}]}, open(a.result_file,"w"))\n''',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_noryx_bridge_is_fail_closed_and_secret_minimizing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    command = _fake_noryx(tmp_path)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", "must-not-leak")
    result = NoryxDeliveryAdapter(command=str(command), receipt_key="n" * 32).run_with_result(
        repository_path=str(repo), objective="Inspect and fix issue", idempotency_key="task-1"
    )
    assert result.result["success"] is True
    assert result.receipt.provider == "noryx"
    assert result.receipt.operation == "run_noryx_delivery"
    assert result.receipt.verify(key="n" * 32)


def test_legacy_nexus_receipt_identity_is_preserved(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    command = _fake_noryx(tmp_path)
    receipt = NexusDeliveryAdapter(command=str(command), receipt_key="x" * 32).run(
        repository_path=str(repo), objective="Legacy task", idempotency_key="legacy-1"
    )
    assert receipt.provider == "nexus"
    assert receipt.operation == "run_nexus_delivery"
    assert receipt.verify(key="x" * 32)
