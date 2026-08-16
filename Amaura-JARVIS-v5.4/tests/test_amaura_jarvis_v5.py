from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from jarvis.amaura.brain import GoalRequest, JarvisBrain
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest, ReferenceResolver, UnifiedMemoryService
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.executor import GovernedReviewRunner
from jarvis.amaura.mission_runner import MissionRunner
from jarvis.amaura.model_gateway import CognitiveModelGateway
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "0")
    monkeypatch.setenv("AMAURA_JARVIS_INTENT_MODEL", "0")
    monkeypatch.setenv("AMAURA_NORYX_INDEPENDENT_VERIFY", "1")


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Amaura Test"], cwd=path, check=True)
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


def _fake_noryx(path: Path, test_command: str) -> Path:
    script = path / "fake_noryx_v5.py"
    script.write_text(
        f"""#!/usr/bin/env python3\nimport argparse,json,pathlib\np=argparse.ArgumentParser(); p.add_argument("command"); p.add_argument("--request-file"); p.add_argument("--result-file"); a=p.parse_args()\nreq=json.load(open(a.request_file)); repo=pathlib.Path(req["repository_path"]); (repo/"changed.py").write_text("VALUE=42\\n")\njson.dump({{"schema":"amaura.noryx-result.v2","success":True,"summary":"done","changed_files":["changed.py"],"tests":[{{"command":{test_command!r},"exit_code":0,"passed":True,"summary":"claimed pass"}}],"evidence":[{{"type":"test","reference":"fixture:test","summary":"claimed"}}],"executor_models":["noryx-fixture-model"]}},open(a.result_file,"w"))\n""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_plan_only_is_draft_and_not_runnable(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        result = brain.submit(GoalRequest(objective="Research release risks", autonomy="plan_only"))
        hierarchy = brain._goal_hierarchy(result["goal"]["id"])
        assert hierarchy
        assert {item["state"] for item in hierarchy} == {TaskState.DRAFT.value}
        assert MissionRunner(control).runnable_goals() == []
        assert brain.status(result["goal"]["id"])["lifecycle_state"] == "planned"
    finally:
        control.close()


def test_antigravity_handoff_is_hard_held_and_cannot_activate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("AMAURA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_MODE", "handoff")
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        result = brain.submit(
            GoalRequest(
                objective="Build a dashboard", workspace=str(repo), autonomy="execute", coding_backend="antigravity"
            )
        )
        goal_id = result["goal"]["id"]
        assert all(item["state"] == TaskState.DRAFT.value for item in brain._goal_hierarchy(goal_id))
        assert not MissionRunner(control).runnable_goals()
        with pytest.raises(GovernanceError, match="Antigravity"):
            brain.activate(goal_id)
    finally:
        control.close()


def test_executable_submission_is_persisted_for_background_runner(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        result = JarvisBrain(control).submit(
            GoalRequest(objective="Research a reliability checklist", autonomy="execute")
        )
        assert result["state"] == "queued"
        assert result["execution"]["background"] is True
        goals = MissionRunner(control).runnable_goals()
        assert [item["id"] for item in goals] == [result["goal"]["id"]]
    finally:
        control.close()


def test_noryx_independent_verifier_rejects_false_test_claim(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    script = _fake_noryx(tmp_path, 'python -c "import sys; sys.exit(7)"')
    with pytest.raises(GovernanceError, match="forbidden in independent verification"):
        NoryxDeliveryAdapter(command=str(script), receipt_key="v" * 32).run_with_result(
            repository_path=str(repo), objective="Fix fixture", idempotency_key="lie"
        )


def test_noryx_independent_verifier_records_real_pass_and_model_provenance(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    script = _fake_noryx(tmp_path, "python -m py_compile changed.py")
    result = NoryxDeliveryAdapter(command=str(script), receipt_key="w" * 32).run_with_result(
        repository_path=str(repo), objective="Fix fixture", idempotency_key="truth"
    )
    assert result.verification["independent_tests"][0]["exit_code"] == 0
    assert result.verification["executor_models"] == ["noryx-fixture-model"]


def test_cognitive_model_gateway_provider_detection_matches_execution_route(monkeypatch: pytest.MonkeyPatch):
    for key in ("NVIDIA_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key")
    monkeypatch.setenv("AMAURA_OPENROUTER_MODEL", "openai/gpt-fixture")
    monkeypatch.setenv("AMAURA_JARVIS_PROVIDER", "openrouter")
    selected = CognitiveModelGateway.select(purpose="planner")
    assert selected.provider == "openrouter"
    assert selected.model == "openai/gpt-fixture"


def test_memory_builds_provenance_graph_and_preserves_superseded_history(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        memory = UnifiedMemoryService(control)
        memory.remember(
            key="coding_choice",
            value="Amaura uses Noryx for Project Orion",
            scope="project",
            actor="founder",
            source="explicit_chat",
        )
        memory.remember(
            key="coding_choice",
            value="Amaura uses Noryx for Project Orion and rejects Backend X",
            scope="project",
            actor="founder",
            source="explicit_chat",
        )
        row = control.store.get_knowledge("jarvis.memory.project", "coding_choice")
        assert row["value"]["trust"] == "founder"
        assert row["value"]["history"]
        graph = memory.graph_context("Noryx Project Orion")
        assert graph["entities"]
        assert graph["relations"]
    finally:
        control.close()


def test_reference_resolver_and_chat_mission_control_pause_resume_cancel(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        created = brain.submit(GoalRequest(objective="Research the Noryx release reliability plan", autonomy="execute"))
        goal_id = created["goal"]["id"]
        resolver = ReferenceResolver(control)
        resolved = resolver.resolve("pause that Noryx release mission")
        assert resolved.resolved
        kernel = ExecutiveKernel(control, conversation_handler=lambda text, context: "ok", brain=brain)
        paused = kernel.handle(ExecutiveRequest(text="pause that Noryx release mission"), allow_missions=True)
        assert paused.intent == "mission_control"
        assert paused.goal_id == goal_id
        assert brain.status(goal_id)["state"] == "held"
        resumed = kernel.handle(ExecutiveRequest(text="resume that Noryx release mission"), allow_missions=True)
        assert resumed.intent == "mission_control"
        assert resumed.goal_id == goal_id
        assert brain.status(goal_id)["lifecycle_state"] == "runnable"
        cancelled = kernel.handle(ExecutiveRequest(text="cancel that Noryx release mission"), allow_missions=True)
        assert cancelled.intent == "mission_control"
        assert brain.status(goal_id)["state"] == "cancelled"
    finally:
        control.close()


def test_dynamic_goal_rolls_up_all_hierarchy_levels(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        result = brain.submit(GoalRequest(objective="Research one release checklist", autonomy="plan_only"))
        goal_id = result["goal"]["id"]
        for task in brain._goal_tasks(goal_id):
            control.store.update_work_item(task["id"], state=TaskState.COMPLETED.value)
        status = brain.status(goal_id)
        assert status["state"] == "completed"
        hierarchy = brain._goal_hierarchy(goal_id)
        parents = [item for item in hierarchy if item["item_type"] != "task"]
        assert parents and all(item["state"] == TaskState.COMPLETED.value for item in parents)
    finally:
        control.close()


def test_review_model_provenance_accepts_external_executor_receipt(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        ref = control.evidence.put_text(
            json.dumps({"actual_model": "noryx-a", "models_used": ["noryx-a", "noryx-b"]}),
            source="test:external-executor",
        ).reference
        task = {"evidence": [{"type": "external_executor_receipt", "reference": ref}]}
        models = GovernedReviewRunner(control)._worker_models_from_evidence(task)
        assert models == {"noryx-a", "noryx-b"}
    finally:
        control.close()
