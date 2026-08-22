from __future__ import annotations

import pytest

import jarvis.reliable_cli as reliable
import jarvis.session_control as session_control


class _Agent:
    pass


class _Brain:
    def __init__(self, mission: dict):
        self.mission = mission
        self.activate_calls: list[str] = []
        self.pause_calls: list[str] = []
        self.cancel_calls: list[str] = []

    def status(self, goal_id: str):
        assert goal_id == self.mission["goal"]["id"]
        return self.mission

    def activate(self, goal_id: str, *, actor: str = "founder"):
        self.activate_calls.append(goal_id)
        self.mission["goal"]["metadata"]["mission_runnable"] = True
        self.mission["state"] = "running"
        self.mission["lifecycle_state"] = "runnable"
        return self.mission

    def pause(self, goal_id: str, *, actor: str = "founder", reason: str = ""):
        self.pause_calls.append(goal_id)
        self.mission["state"] = "held"
        self.mission["lifecycle_state"] = "held"
        self.mission["goal"]["metadata"]["mission_runnable"] = False
        return self.mission

    def cancel(self, goal_id: str, *, actor: str = "founder", reason: str = ""):
        self.cancel_calls.append(goal_id)
        self.mission["state"] = "cancelled"
        self.mission["lifecycle_state"] = "cancelled"
        return self.mission


class _Kernel:
    def __init__(self, brain: _Brain):
        self.brain = brain


class _Control:
    founder_id = "founder"

    def __init__(self, brain: _Brain):
        self.brain = brain
        self.decisions: list[tuple[str, str, str, str]] = []

    def decide_approval(self, approval_id: str, actor: str, decision: str, reason: str):
        self.decisions.append((approval_id, actor, decision, reason))
        self.brain.mission["pending_approvals"] = []
        self.brain.mission["state"] = "completed"
        self.brain.mission["lifecycle_state"] = "completed"
        return {"approval": {"id": approval_id, "status": decision}}


def _mission(*, runnable: bool, state: str = "queued", pending: list[dict] | None = None) -> dict:
    return {
        "goal": {
            "id": "goal_streetfighter",
            "title": "Street Fighter-like game",
            "state": "assigned" if runnable else "draft",
            "metadata": {"dynamic_goal": True, "mission_runnable": runnable},
        },
        "state": state,
        "lifecycle_state": "runnable" if runnable else "planned",
        "states": {"assigned": 1},
        "tasks": [{"id": "task_builder", "title": "Implement the objective", "state": "assigned"}],
        "active_tasks": [],
        "pending_approvals": list(pending or []),
    }


def _bind(agent: _Agent) -> None:
    reliable._session_bindings(agent)["cli"] = "goal_streetfighter"


def test_exact_real_followup_phrases_are_bound_controls() -> None:
    assert session_control._explicit_bound_control_language("approve the task for street fighter build it") is True
    assert session_control._explicit_bound_control_language("ignore that first build street fighter focus on that") is True
    assert session_control._explicit_bound_control_language("execute it and build full game") is True
    assert session_control._explicit_bound_control_language("yes") is True
    assert session_control._explicit_bound_control_language("build a snake game") is False


def test_planned_bound_goal_is_activated_instead_of_creating_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    _bind(agent)
    brain = _Brain(_mission(runnable=False))
    control = _Control(brain)
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: _Kernel(brain))
    monkeypatch.setattr(
        session_control,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create a new mission")),
    )

    result = session_control.session_bound_run_executive(
        agent,
        "approve the task for street fighter build it",
        control=control,
        session_id="cli",
    )

    assert result["goal_id"] == "goal_streetfighter"
    assert result["frontdoor"]["session_bound_control"] is True
    assert result["frontdoor"]["action"] == "activate"
    assert result["frontdoor"]["changed"] is True
    assert brain.activate_calls == ["goal_streetfighter"]
    assert "No duplicate mission was created" in result["message"]


def test_running_bound_goal_execute_it_is_noop_not_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    _bind(agent)
    brain = _Brain(_mission(runnable=True, state="running"))
    control = _Control(brain)
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: _Kernel(brain))
    monkeypatch.setattr(
        session_control,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create a duplicate mission")),
    )

    for prompt in (
        "ignore that first build street fighter focus on that",
        "execute it and build full game",
    ):
        result = session_control.session_bound_run_executive(agent, prompt, control=control, session_id="cli")
        assert result["goal_id"] == "goal_streetfighter"
        assert result["frontdoor"]["action"] == "continue_existing"
        assert result["frontdoor"]["changed"] is False
        assert "No duplicate goal was created" in result["message"]

    assert brain.activate_calls == []


def test_new_unrelated_project_still_reaches_normal_mission_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    _bind(agent)
    brain = _Brain(_mission(runnable=True, state="running"))
    control = _Control(brain)
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: _Kernel(brain))
    calls: list[str] = []

    def previous(self, user_input: str, **kwargs):
        calls.append(user_input)
        return {"intent": "mission", "message": "created", "goal_id": "goal_snake", "result": {}}

    monkeypatch.setattr(session_control, "_PREVIOUS_RUN_EXECUTIVE", previous)

    result = session_control.session_bound_run_executive(
        agent,
        "build a snake game",
        control=control,
        session_id="cli",
    )

    assert result["goal_id"] == "goal_snake"
    assert calls == ["build a snake game"]


def test_bare_yes_activates_only_current_planned_goal(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    _bind(agent)
    brain = _Brain(_mission(runnable=False))
    control = _Control(brain)
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: _Kernel(brain))

    result = session_control._bound_control_response(agent, "yes", control=control, session_id="cli")

    assert result is not None
    assert result["goal_id"] == "goal_streetfighter"
    assert result["result"]["action"] == "activate"
    assert brain.activate_calls == ["goal_streetfighter"]
    assert control.decisions == []


def test_bare_yes_approves_only_single_pending_current_goal_consequence(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    _bind(agent)
    brain = _Brain(
        _mission(
            runnable=True,
            state="awaiting_approval",
            pending=[{"id": "approval_current", "task_id": "task_builder"}],
        )
    )
    brain.mission["lifecycle_state"] = "runnable"
    control = _Control(brain)
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: _Kernel(brain))

    result = session_control._bound_control_response(agent, "yes", control=control, session_id="cli")

    assert result is not None
    assert result["goal_id"] == "goal_streetfighter"
    assert result["result"]["action"] == "approve"
    assert len(control.decisions) == 1
    assert control.decisions[0][0] == "approval_current"


def test_multiple_current_goal_approvals_require_explicit_id(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    _bind(agent)
    brain = _Brain(
        _mission(
            runnable=True,
            state="awaiting_approval",
            pending=[{"id": "approval_1"}, {"id": "approval_2"}],
        )
    )
    brain.mission["lifecycle_state"] = "runnable"
    control = _Control(brain)
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: _Kernel(brain))

    result = session_control._bound_control_response(agent, "yes", control=control, session_id="cli")

    assert result is not None
    assert result["result"]["action"] == "approval_ambiguous"
    assert result["result"]["changed"] is False
    assert control.decisions == []


def test_bare_yes_without_bound_goal_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    calls: list[str] = []

    def previous(self, user_input: str, **kwargs):
        calls.append(user_input)
        return {"intent": "conversation", "message": "clarified", "result": {}}

    monkeypatch.setattr(session_control, "_PREVIOUS_RUN_EXECUTIVE", previous)

    result = session_control.session_bound_run_executive(agent, "yes", control=object(), session_id="cli")

    assert result["message"] == "clarified"
    assert calls == ["yes"]
