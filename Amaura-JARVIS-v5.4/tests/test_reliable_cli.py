from __future__ import annotations

import threading
from pathlib import Path

import pytest

import jarvis.reliable_cli as reliable
from jarvis.amaura.models import GovernanceError


def test_real_goal_result_query_is_forced_to_durable_status() -> None:
    assert reliable._forced_intent("goal_b75d3d75ecfb give me results of this goal") == "status"
    assert reliable._forced_intent("show progress for task_705167d6038b") == "status"


def test_real_vague_followup_from_terminal_session_is_recognized() -> None:
    assert reliable._is_vague_work_item_result_query("what are the results of task i gave you") is True
    assert reliable._is_vague_work_item_result_query("show status of that mission") is True
    assert reliable._is_vague_work_item_result_query("progress on my project") is True
    assert reliable._is_vague_work_item_result_query("what are the results of goal_abc123") is False
    assert reliable._is_vague_work_item_result_query("what is the status of global markets?") is False


def test_real_repository_audit_phrase_is_forced_to_governed_mission() -> None:
    assert reliable._forced_intent("no go through amaura jarvis folder give full audit") == "mission"
    assert reliable._forced_intent("deep dive into this repository and audit it") == "mission"
    assert reliable._forced_intent("inspect the current codebase for reliability bugs") == "mission"


def test_new_project_isolation_does_not_treat_current_checkout_as_target() -> None:
    prompt = 'ok create a supermario game and save it as "sexy" in desktop'
    assert reliable._is_new_software_project(prompt) is True
    assert reliable._forced_intent(prompt) == "mission"

    assert reliable._is_new_software_project("fix this repository and run its tests") is False
    assert reliable._is_new_software_project("debug /tmp/existing-repo") is False


def test_ordinary_conversation_and_app_control_are_not_stolen() -> None:
    assert reliable._forced_intent("hi tell me all your capabilities") is None
    assert reliable._forced_intent("how are you doing today?") is None
    assert reliable._forced_intent("open calculator") is None
    assert reliable._forced_intent("quit safari") is None


def test_session_goal_binding_is_isolated_per_cli_session() -> None:
    class Agent:
        pass

    agent = Agent()
    reliable._remember_session_goal(agent, "session-a", {"goal_id": "goal_streetfighter"})
    reliable._remember_session_goal(agent, "session-b", {"goal_id": "goal_other"})

    assert reliable._session_bindings(agent)["session-a"] == "goal_streetfighter"
    assert reliable._session_bindings(agent)["session-b"] == "goal_other"


def test_vague_followup_reads_same_session_mission_not_global_history(monkeypatch: pytest.MonkeyPatch) -> None:
    class Agent:
        pass

    class Brain:
        @staticmethod
        def status(goal_id: str):
            assert goal_id == "goal_streetfighter"
            return {
                "goal": {"id": goal_id, "title": "Street Fighter Game", "state": "assigned"},
                "state": "queued",
                "states": {"assigned": 1},
                "tasks": [
                    {
                        "id": "task_game",
                        "title": "Build Street Fighter Game",
                        "state": "assigned",
                        "summary": "",
                    }
                ],
                "active_tasks": [],
                "pending_approvals": [],
            }

    class Kernel:
        brain = Brain()

    def should_not_fall_back(*args, **kwargs):
        raise AssertionError("vague same-session follow-up must not enter global/model resolver")

    agent = Agent()
    reliable._session_bindings(agent)["cli-1"] = "goal_streetfighter"
    monkeypatch.setattr(reliable, "_kernel_for", lambda agent, control: Kernel())
    monkeypatch.setattr(reliable, "_ORIGINAL_RUN_EXECUTIVE", should_not_fall_back)

    result = reliable.reliable_run_executive(
        agent,
        "what are the results of task i gave you",
        control=object(),
        session_id="cli-1",
    )

    assert result["goal_id"] == "goal_streetfighter"
    assert result["state"] == "queued"
    assert result["result"]["session_bound"] is True
    assert result["frontdoor"]["session_bound_status"] is True
    assert "Street Fighter Game" in result["message"]
    assert "No completed task result has been recorded yet" in result["message"]
    assert "developer-tool" not in result["message"]


def test_forced_and_normal_paths_reuse_same_executive_kernel() -> None:
    class Agent:
        pass

    agent = Agent()
    control = object()
    existing_kernel = object()
    agent._executive_lock = threading.Lock()
    agent._executive_kernel = existing_kernel
    agent._executive_control = control

    assert reliable._kernel_for(agent, control) is existing_kernel


def test_transient_cognition_unavailable_gets_one_bounded_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run(self, user_input: str, **kwargs):
        calls.append(user_input)
        if len(calls) == 1:
            return {"intent": "conversation", "message": reliable._UNAVAILABLE_MESSAGE}
        return {"intent": "conversation", "message": "Recovered answer", "result": {}}

    monkeypatch.setattr(reliable, "_ORIGINAL_RUN_EXECUTIVE", fake_run)
    monkeypatch.setattr(reliable.time, "sleep", lambda _: None)

    result = reliable.reliable_run_executive(object(), "tell me something useful", control=object())

    assert result["message"] == "Recovered answer"
    assert result["frontdoor"]["transient_retry"] is True
    assert calls == ["tell me something useful", "tell me something useful"]


def test_unexpected_runtime_error_is_contained_and_cli_can_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self, user_input: str, **kwargs):
        raise RuntimeError("simulated provider/runtime fault")

    monkeypatch.setattr(reliable, "_ORIGINAL_RUN_EXECUTIVE", explode)

    result = reliable.reliable_run_executive(object(), "normal conversation", control=object())

    assert result["state"] == "failed"
    assert result["result"]["frontdoor_recovered"] is True
    assert "remains online" in result["message"]
    assert "simulated provider/runtime fault" not in result["message"]


def test_governance_rejection_is_safe_and_does_not_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args, **kwargs):
        raise GovernanceError("QA Agent may not own medium-risk work")

    monkeypatch.setattr(reliable, "_run_forced", reject)

    result = reliable.reliable_run_executive(
        object(),
        "go through this repository and audit it",
        control=object(),
    )

    assert result["state"] == "rejected"
    assert result["result"]["error_type"] == "governance"
    assert "JARVIS remains online" in result["message"]


def test_packaged_jarvis_entrypoint_installs_all_runtime_guards() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'jarvis = "jarvis.runtime_entry:main"' in text
