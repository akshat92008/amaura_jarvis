from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
from jarvis.amaura.brain import GoalRequest, JarvisBrain
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.mission_runner import MissionRunner
from jarvis.amaura.model_gateway import CognitiveModelGateway
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.verification import SecureVerifierRunner


@pytest.fixture(autouse=True)
def _stable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "0")
    monkeypatch.setenv("AMAURA_JARVIS_INTENT_MODEL", "0")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_MODE", "cli")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_AUTONOMY_SETTINGS", "0")
    monkeypatch.setenv("AMAURA_VERIFIER_MODE", "host")
    monkeypatch.setenv("AMAURA_ALLOW_HOST_VERIFICATION", "1")


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Amaura Test"], cwd=path, check=True)
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


def _fake_agy(path: Path, *, test_command: str = "python -m py_compile agy_fix.py") -> Path:
    script = path / "agy"
    script.write_text(
        f'''#!/usr/bin/env python3
import json, pathlib, sys
if "--version" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == "version"):
    print("Antigravity CLI v1.1.11"); raise SystemExit(0)
assert "--sandbox" in sys.argv
assert "--new-project" in sys.argv
assert "--project=default-cli-project" not in sys.argv
assert "--add-dir" in sys.argv and pathlib.Path(sys.argv[sys.argv.index("--add-dir")+1]).resolve() == pathlib.Path.cwd().resolve()
assert "--mode" in sys.argv and sys.argv[sys.argv.index("--mode")+1] == "accept-edits"
assert "--output-format" in sys.argv and sys.argv[sys.argv.index("--output-format")+1] == "stream-json"
assert "--json-schema" in sys.argv
assert "--print-timeout" in sys.argv
assert "--dangerously-skip-permissions" not in sys.argv
assert "-p" in sys.argv
prompt=sys.argv[sys.argv.index("-p")+1]
assert str(pathlib.Path.cwd().resolve()) in prompt
# Removed from prompt: sandbox instruction now tells the model to avoid git
# commands that fail under macOS sandbox (git status, git diff, pwd).
# Assert the replacement constraint is present instead.
assert "Strict Sandbox Constraints" in prompt
repo=pathlib.Path.cwd(); (repo/"agy_fix.py").write_text("VALUE = 51\\n")
result={{"schema":"amaura.antigravity-result.v1","success":True,"summary":"Implemented the requested change","changed_files":["agy_fix.py"],"verification_commands":[{test_command!r}],"remaining_failures":[],"models_used":["gemini-fixture"],"conversation_id":"agy-fixture-1"}}
print(json.dumps({{"result": result, "usage": {{"total_tokens": 42}}}}))
''',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_antigravity_cli_structured_sandboxed_delivery_and_independent_verification(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    agy = _fake_agy(tmp_path)
    result = AntigravityDeliveryAdapter(command=str(agy), receipt_key="a" * 32).run_with_result(
        repository_path=str(repo), objective="Implement fixture", idempotency_key="agy-test"
    )
    assert result.receipt.provider == "antigravity"
    assert result.cli_version == "1.1.11"
    assert result.verification["changed_files"] == ["agy_fix.py"]
    assert result.verification["antigravity_sandbox_requested"] is True
    assert result.verification["independent_tests"][0]["passed"] is True
    assert result.verification["executor_models"] == ["gemini-fixture"]


def test_antigravity_requires_modern_structured_cli(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    agy = tmp_path / "agy"
    agy.write_text('#!/bin/sh\necho "Antigravity CLI v1.1.7"\n', encoding="utf-8")
    agy.chmod(agy.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(GovernanceError, match=">=1.1.8"):
        AntigravityDeliveryAdapter(command=str(agy), receipt_key="a" * 32).run_with_result(
            repository_path=str(repo), objective="Implement fixture", idempotency_key="old"
        )


def test_antigravity_verifier_rejects_inline_python_and_path_alias():
    with pytest.raises(GovernanceError, match="Inline Python"):
        SecureVerifierRunner.parse_command('python -c "print(1)"')
    with pytest.raises(GovernanceError, match="not a path"):
        SecureVerifierRunner.parse_command('/tmp/python -m pytest')


def test_antigravity_is_runnable_backend_not_handoff_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        result = JarvisBrain(control).submit(GoalRequest(
            objective="Build a tested dashboard", workspace=str(repo), autonomy="execute", coding_backend="antigravity"
        ))
        assert result["state"] == "queued"
        goal = control.store.get_work_item(result["goal"]["id"])
        assert goal["metadata"]["mission_runnable"] is True
        assert goal["metadata"]["antigravity_handoff"] is False
        assert MissionRunner(control).runnable_goals()
    finally:
        control.close()


def test_low_level_claim_refuses_stale_assigned_task_from_held_mission(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        created = brain.submit(GoalRequest(objective="Research release risks", autonomy="plan_only"))
        task = brain.status(created["goal"]["id"])["tasks"][0]
        control.store.update_work_item(task["id"], state=TaskState.ASSIGNED.value)
        claim = control.store.claim_next_task(worker_id="test-worker", workflow_id=task["workflow_id"])
        assert claim is None
        assert control.store.get_work_item(task["id"])["state"] == TaskState.DRAFT.value
    finally:
        control.close()


def test_pause_freezes_awaiting_review_and_resume_restores_it(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        created = brain.submit(GoalRequest(objective="Research launch risks", autonomy="execute"))
        goal_id = created["goal"]["id"]
        task = brain.status(goal_id)["tasks"][0]
        control.store.update_work_item(task["id"], state=TaskState.AWAITING_REVIEW.value)
        brain.pause(goal_id)
        paused = control.store.get_work_item(task["id"])
        assert paused["state"] == TaskState.DRAFT.value
        assert paused["metadata"]["mission_pause_previous_state"] == TaskState.AWAITING_REVIEW.value
        brain.activate(goal_id)
        resumed = control.store.get_work_item(task["id"])
        assert resumed["state"] == TaskState.AWAITING_REVIEW.value
    finally:
        control.close()


def test_generation_token_rejects_stale_running_worker(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        created = brain.submit(GoalRequest(objective="Research launch risks", autonomy="execute"))
        goal_id = created["goal"]["id"]
        task = brain.status(goal_id)["tasks"][0]
        control.store.update_work_item(task["id"], state=TaskState.IN_PROGRESS.value)
        brain.pause(goal_id)
        with pytest.raises(GovernanceError, match="paused|authority|generation"):
            GovernedTaskRunner(control)._ensure_task_active(task["id"])
    finally:
        control.close()


def test_ollama_executive_uses_company_local_model(monkeypatch: pytest.MonkeyPatch):
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AMAURA_JARVIS_PROVIDER", "ollama")
    monkeypatch.setenv("AMAURA_JARVIS_OLLAMA_PROBE", "0")
    monkeypatch.setenv("AMAURA_LOCAL_MODEL", "nova:3b")
    monkeypatch.delenv("AMAURA_JARVIS_MODEL", raising=False)
    monkeypatch.delenv("AMAURA_OLLAMA_MODEL", raising=False)
    selected = CognitiveModelGateway.select(purpose="planner")
    assert selected is not None
    assert selected.provider == "ollama"
    assert selected.model == "nova:3b"


def test_mission_runner_backoff_records_configuration_wait(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        created = brain.submit(GoalRequest(objective="Research launch risks", autonomy="execute"))
        runner = MissionRunner(control)
        detail = runner._record_failure(created["goal"]["id"], GovernanceError("Antigravity CLI is not installed"))
        assert detail["class"] == "waiting_configuration"
        goal = control.store.get_work_item(created["goal"]["id"])
        assert goal["metadata"]["runner_next_attempt_at"]
        assert goal not in runner.runnable_goals()
    finally:
        control.close()


def test_manual_antigravity_handoff_remains_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_MODE", "handoff")
    monkeypatch.setenv("AMAURA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        result = JarvisBrain(control).submit(GoalRequest(
            objective="Build a dashboard", workspace=str(repo), autonomy="execute", coding_backend="antigravity"
        ))
        assert result["state"] == "handoff_required"
        assert result["requires_founder_action"] is True
        assert not MissionRunner(control).runnable_goals()
    finally:
        control.close()

def test_antigravity_settings_reject_unsandboxed_and_global_file_or_web_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "toolPermission": "proceed-in-sandbox",
        "artifactReviewPolicy": "always-proceed",
        "allowNonWorkspaceAccess": False,
        "enableTerminalSandbox": True,
        "permissions": {"allow": ["unsandboxed(git push)", "read_url(*)", "write_file(*)"]},
    }), encoding="utf-8")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_SETTINGS", str(settings))
    status = AntigravityDeliveryAdapter.settings_status()
    assert status["automation_ready"] is False
    assert "unsandboxed(git push)" in status["risky_global_allows"]
    assert "read_url(*)" in status["risky_global_allows"]
    assert "write_file(*)" in status["risky_global_allows"]


def test_default_executive_coding_backend_is_antigravity():
    from jarvis.amaura.cognition import ExecutiveRequest
    assert ExecutiveRequest(text="Build the app").coding_backend == "antigravity"
    assert GoalRequest(objective="Build the app").coding_backend == "antigravity"
