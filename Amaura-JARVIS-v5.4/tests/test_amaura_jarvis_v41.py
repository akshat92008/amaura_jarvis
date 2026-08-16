from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from jarvis.amaura.brain import GoalRequest, JarvisBrain
from jarvis.amaura.cognition import (
    ExecutiveKernel,
    ExecutiveRequest,
    IntentEngine,
    ProactiveCognition,
    UnifiedMemoryService,
    WorldModel,
)
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter
from jarvis.voice.duplex_voice import DuplexVoiceEngine


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Amaura Test"], cwd=path, check=True)
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


@pytest.fixture(autouse=True)
def _deterministic_cognition(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "0")
    monkeypatch.setenv("AMAURA_JARVIS_LLM_INTENT", "0")


def test_intent_engine_routes_questions_and_explicit_work():
    engine = IntentEngine()
    assert engine.classify("What is the current release status?") == "conversation"
    assert engine.classify("Build the dashboard and run the tests") == "mission"
    assert engine.classify("Remember that Noryx owns repository engineering") == "memory_write"


def test_lightning_path_skips_heavy_context_and_consolidates_after_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A normal question must not pay for world/reference/memory model work."""
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        kernel = ExecutiveKernel(control, conversation_handler=lambda text, context: f"ANSWER:{text}")
        monkeypatch.setattr(
            kernel.world, "context", lambda *_args, **_kwargs: pytest.fail("world lookup on chat fast path")
        )
        monkeypatch.setattr(
            kernel.memory, "context", lambda *_args, **_kwargs: pytest.fail("memory lookup on chat fast path")
        )
        monkeypatch.setattr(
            kernel.references, "resolve", lambda *_args, **_kwargs: pytest.fail("reference lookup on chat fast path")
        )
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            kernel,
            "_consolidate_async",
            lambda *, user_text, assistant_text, session_id: calls.append((user_text, assistant_text)),
        )
        result = kernel.handle(ExecutiveRequest(text="Why is the sky blue?", session_id="fast"))
        assert result.intent == "conversation"
        assert result.message == "ANSWER:Why is the sky blue?"
        assert calls == [("Why is the sky blue?", "ANSWER:Why is the sky blue?")]
    finally:
        control.close()


def test_lightning_path_retains_short_session_history(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    contexts: list[str] = []
    try:

        def reply(text: str, context: str) -> str:
            contexts.append(context)
            return f"ANSWER:{text}"

        kernel = ExecutiveKernel(control, conversation_handler=reply)
        kernel.handle(ExecutiveRequest(text="Hello", session_id="history"))
        kernel.handle(ExecutiveRequest(text="What did I just say?", session_id="history"))
        assert "User: Hello" in contexts[-1]
        assert "Assistant: ANSWER:Hello" in contexts[-1]
    finally:
        control.close()


def test_status_reuses_one_world_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        world = WorldModel(control)
        original_refresh = world.refresh
        refresh_count = 0

        def counted_refresh(*args, **kwargs):
            nonlocal refresh_count
            refresh_count += 1
            return original_refresh(*args, **kwargs)

        monkeypatch.setattr(world, "refresh", counted_refresh)
        kernel = ExecutiveKernel(control, conversation_handler=lambda text, context: "ok", world=world)
        response = kernel.handle(ExecutiveRequest(text="company status"))
        assert response.intent == "status"
        assert refresh_count == 1
    finally:
        control.close()


def test_executive_kernel_is_one_front_door_and_fail_closed_without_operator(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        kernel = ExecutiveKernel(control, conversation_handler=lambda text, context: f"ANSWER:{text}")
        answer = kernel.handle(ExecutiveRequest(text="Explain our release state"), allow_missions=False)
        assert answer.intent == "conversation"
        assert answer.message.startswith("ANSWER:")

        denied = kernel.handle(ExecutiveRequest(text="Build a tested API feature"), allow_missions=False)
        assert denied.intent == "mission"
        assert denied.state == "authorization_required"
        assert control.store.list_work_items(item_type="programme", limit=20) == []
    finally:
        control.close()


def test_executive_kernel_materializes_authorized_mission(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        kernel = ExecutiveKernel(control, conversation_handler=lambda text, context: "ok")
        result = kernel.handle(
            ExecutiveRequest(text="Research a release checklist", autonomy="plan_only"),
            allow_missions=True,
        )
        assert result.intent == "mission"
        assert result.goal_id
        assert result.state in {"created", "queued", "planned"}
        status = JarvisBrain(control).status(result.goal_id)
        assert status["tasks"]
    finally:
        control.close()


def test_unified_memory_and_world_model_share_authoritative_company_state(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        memory = UnifiedMemoryService(control)
        memory.remember(
            key="noryx_role",
            value="Noryx is the canonical repository engineering backend",
            scope="project",
            confidence=0.95,
            source="test",
        )
        hits = memory.query("Noryx repository engineering", limit=10)
        assert any("Noryx" in json.dumps(hit.content) for hit in hits)
        snapshot = WorldModel(control).refresh()
        stored = control.store.get_knowledge("jarvis.world", "current")
        assert stored["value"]["captured_at"] == snapshot["captured_at"]
    finally:
        control.close()


def test_replanning_mutates_dag_and_preserves_failed_history(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        brain = JarvisBrain(control)
        submitted = brain.submit(
            GoalRequest(
                objective="Build a tested API feature",
                workspace=str(repo),
                autonomy="plan_only",
                coding_backend="internal",
                max_replans=2,
            )
        )
        goal_id = submitted["goal"]["id"]
        brain.activate(goal_id)
        tasks = brain.status(goal_id)["tasks"]
        implementation = next(t for t in tasks if (t.get("metadata") or {}).get("step_key") == "implementation")
        verification = next(t for t in tasks if (t.get("metadata") or {}).get("step_key") == "verification")
        assert implementation["id"] in verification["dependencies"]

        failed_metadata = dict(implementation.get("metadata") or {})
        failed_metadata.update(
            {
                "engineering_phase": "executor_started",
                "antigravity_pid": 12345,
                "git_worktree_path": "/tmp/stale-worktree",
            }
        )
        control.store.update_work_item(
            implementation["id"],
            state=TaskState.FAILED.value,
            summary="Implementation failed because the selected architecture conflicts with the fixture API.",
            metadata=failed_metadata,
        )
        created = brain._replan_failed(goal_id)
        assert len(created) == 2
        created_by_key = {(t.get("metadata") or {}).get("step_key"): t for t in created}
        diagnose = next(t for key, t in created_by_key.items() if str(key).startswith("diagnose_"))
        repair = next(t for key, t in created_by_key.items() if str(key).startswith("repair_"))
        assert diagnose["id"] in repair["dependencies"]
        for replacement in created:
            replacement_metadata = replacement.get("metadata") or {}
            assert "engineering_phase" not in replacement_metadata
            assert "antigravity_pid" not in replacement_metadata
            assert "git_worktree_path" not in replacement_metadata

        failed_after = control.store.get_work_item(implementation["id"])
        assert repair["id"] in (failed_after.get("metadata") or {})["superseded_by"]
        verification_after = control.store.get_work_item(verification["id"])
        assert implementation["id"] not in verification_after["dependencies"]
        assert repair["id"] in verification_after["dependencies"]
        goal_after = control.store.get_work_item(goal_id)
        assert (goal_after.get("metadata") or {})["replans_used"] == 1
        assert (goal_after.get("metadata") or {})["plan_revision_history"]
    finally:
        control.close()


def _write_fake_noryx(path: Path, source: str) -> Path:
    script = path / "fake_noryx.py"
    script.write_text(source, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_noryx_rejects_exit_zero_without_engineering_evidence(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    script = _write_fake_noryx(
        tmp_path,
        """#!/usr/bin/env python3\nimport argparse,json\np=argparse.ArgumentParser(); p.add_argument("command"); p.add_argument("--request-file"); p.add_argument("--result-file"); a=p.parse_args()\njson.dump({"success":True}, open(a.result_file,"w"))\n""",
    )
    with pytest.raises(GovernanceError, match="evidence contract"):
        NoryxDeliveryAdapter(command=str(script), receipt_key="z" * 32).run_with_result(
            repository_path=str(repo), objective="Fix the fixture", idempotency_key="weak-result"
        )


def test_noryx_verifies_git_delta_tests_and_secret_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", "must-never-leak")
    script = _write_fake_noryx(
        tmp_path,
        """#!/usr/bin/env python3\nimport argparse,json,os,pathlib\np=argparse.ArgumentParser(); p.add_argument("command"); p.add_argument("--request-file"); p.add_argument("--result-file"); a=p.parse_args()\nreq=json.load(open(a.request_file)); assert req["requirements"]["result_schema"]=="amaura.noryx-result.v2"; assert "AMAURA_OPERATOR_KEY" not in os.environ\nrepo=pathlib.Path(req["repository_path"]); (repo/"feature.py").write_text("VALUE = 41 + 1\\n")\njson.dump({"schema":"amaura.noryx-result.v2","success":True,"summary":"Implemented the verified fixture feature","changed_files":["feature.py"],"tests":[{"command":"python -m py_compile feature.py","exit_code":0,"passed":True,"summary":"compiled"}],"evidence":[{"type":"test","reference":"fixture:compile","summary":"compile passed"}]},open(a.result_file,"w"))\n""",
    )
    result = NoryxDeliveryAdapter(command=str(script), receipt_key="n" * 32).run_with_result(
        repository_path=str(repo), objective="Implement the fixture", idempotency_key="strong-result"
    )
    assert result.verification["changed_files"] == ["feature.py"]
    assert result.verification["tests"][0]["exit_code"] == 0
    assert len(result.verification["diff_hash"]) == 64


class _CompletedThread:
    def join(self, timeout=None):
        return None


class _FakeSpeaker:
    def __init__(self):
        self.spoken: list[str] = []
        self._speaking = False

    def speak_async(self, text: str):
        self.spoken.append(text)
        return _CompletedThread()

    def stop(self):
        self._speaking = False

    def is_speaking(self):
        return self._speaking


def test_voice_push_to_talk_calls_real_command_handler_not_canned_text():
    speaker = _FakeSpeaker()
    calls: list[str] = []
    engine = DuplexVoiceEngine(
        command_handler=lambda text: calls.append(text) or f"REAL:{text}",
        speaker=speaker,
    )
    output = engine.push_to_talk("check Noryx")
    assert calls == ["check Noryx"]
    assert "REAL:check Noryx" in output
    assert speaker.spoken == ["REAL:check Noryx"]
    assert "Processing your request" not in output
    assert engine.last_latency_ms is not None


def test_proactive_cognition_is_persisted(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        control.store.create_alert(
            {
                "id": "alert-test",
                "severity": "warning",
                "code": "fixture_regression",
                "message": "Fixture regression requires investigation",
                "resource_id": "fixture",
                "details": {"source": "test"},
            }
        )
        insights = ProactiveCognition(control).scan()
        assert any(item["code"] == "fixture_regression" for item in insights)
        stored = control.store.get_knowledge("jarvis.proactive", "latest")
        assert stored["value"]["insights"]
    finally:
        control.close()


def test_unified_memory_clear_scope_preserves_other_scope(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        memory = UnifiedMemoryService(control)
        memory.remember(key="personal_fact", value="prefers concise reports", scope="personal")
        memory.remember(key="project_fact", value="Noryx is engineering backend", scope="project")
        removed = memory.clear_scope(scope="personal")
        assert removed >= 1
        assert not any(row.get("key") == "personal_fact" for row in memory.list(scope="personal"))
        assert any(row.get("key") == "project_fact" for row in memory.list(scope="project"))
    finally:
        control.close()


def test_private_intelligence_benchmark_harness_runs_cognitive_pack(tmp_path: Path):
    from jarvis.amaura.intelligence_benchmark import run_benchmark

    pack = tmp_path / "pack.json"
    pack.write_text(
        json.dumps(
            {
                "version": 1,
                "cognitive": [
                    {"id": "explain", "prompt": "Explain our release architecture", "expected_intent": "conversation"},
                    {
                        "id": "build",
                        "prompt": "Build a tested API feature",
                        "expected_intent": "mission",
                        "max_tasks": 8,
                        "forbidden_action_types": ["payment", "public_publish"],
                    },
                ],
                "engineering": [],
            }
        ),
        encoding="utf-8",
    )
    result = run_benchmark(pack_path=pack)
    assert result.attempted == 2
    assert result.passed == 2
    assert result.failed == 0
