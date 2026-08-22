from __future__ import annotations

import pytest

import jarvis.reliable_cli as reliable
import jarvis.session_control as session_control


def test_bound_control_error_never_falls_through_to_new_mission(monkeypatch: pytest.MonkeyPatch) -> None:
    class Agent:
        pass

    class Brain:
        @staticmethod
        def status(goal_id: str):
            assert goal_id == "goal_streetfighter"
            return {
                "goal": {
                    "id": goal_id,
                    "title": "Street Fighter-like game",
                    "metadata": {"dynamic_goal": True, "mission_runnable": False},
                },
                "state": "queued",
                "lifecycle_state": "planned",
                "states": {"draft": 1},
                "tasks": [],
                "pending_approvals": [],
            }

        @staticmethod
        def activate(goal_id: str, *, actor: str = "founder"):
            raise RuntimeError("simulated activation failure")

    class Kernel:
        brain = Brain()

    agent = Agent()
    reliable._session_bindings(agent)["cli"] = "goal_streetfighter"
    monkeypatch.setattr(session_control, "_kernel_for", lambda agent, control: Kernel())
    monkeypatch.setattr(
        session_control,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fall through and create a goal")),
    )

    result = session_control.session_bound_run_executive(
        agent,
        "execute it and build full game",
        control=object(),
        session_id="cli",
    )

    assert result["goal_id"] == "goal_streetfighter"
    assert result["state"] == "failed"
    assert result["result"]["action"] == "control_error"
    assert result["result"]["changed"] is False
    assert result["result"]["error_type"] == "RuntimeError"
    assert "did not create a new mission" in result["message"]
