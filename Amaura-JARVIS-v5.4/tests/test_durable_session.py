from __future__ import annotations

import pytest

import jarvis.durable_session as durable
import jarvis.reliable_cli as reliable


class _Agent:
    pass


class _Store:
    def __init__(self, items: list[dict]):
        self.items = items

    def list_work_items(self, *, item_type: str | None = None, limit: int = 1000):
        assert item_type == "programme"
        return list(self.items)[:limit]


class _Control:
    def __init__(self, items: list[dict]):
        self.store = _Store(items)


def _goal(goal_id: str, session_id: str, when: str) -> dict:
    """Match JarvisBrain._materialize's real persisted programme shape."""
    return {
        "id": goal_id,
        "item_type": "programme",
        "title": goal_id,
        "state": "assigned",
        "created_at": when,
        "updated_at": when,
        "metadata": {
            "dynamic_goal": True,
            "goal_request": {
                "objective": "build a game like street fighter with sounds",
                "metadata": {"executive_session_id": session_id},
            },
        },
    }


def _legacy_top_level_goal(goal_id: str, session_id: str, when: str) -> dict:
    return {
        "id": goal_id,
        "item_type": "programme",
        "title": goal_id,
        "state": "assigned",
        "created_at": when,
        "updated_at": when,
        "metadata": {"dynamic_goal": True, "executive_session_id": session_id},
    }


def test_latest_session_goal_uses_canonical_nested_goal_request_metadata() -> None:
    control = _Control(
        [
            _goal("goal_old_other", "other-session", "2026-08-23T00:00:00+05:30"),
            _goal("goal_streetfighter_old", "cli-1", "2026-08-23T00:01:00+05:30"),
            _goal("goal_streetfighter_new", "cli-1", "2026-08-23T00:03:00+05:30"),
        ]
    )

    assert durable.latest_session_goal(control, "cli-1") == "goal_streetfighter_new"
    assert durable.latest_session_goal(control, "missing") == ""


def test_latest_session_goal_accepts_legacy_top_level_session_metadata() -> None:
    control = _Control([_legacy_top_level_goal("goal_legacy", "cli-legacy", "2026-08-23T00:03:00+05:30")])
    assert durable.latest_session_goal(control, "cli-legacy") == "goal_legacy"


def test_durable_guard_recovers_missing_in_memory_binding_before_next_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    control = _Control([_goal("goal_current", "cli-1", "2026-08-23T00:03:00+05:30")])
    seen: list[str] = []

    def previous(self, user_input: str, **kwargs):
        seen.append(reliable._session_bindings(self).get("cli-1", ""))
        return {"intent": "conversation", "message": "ok", "result": {}}

    monkeypatch.setattr(durable, "_PREVIOUS_RUN_EXECUTIVE", previous)

    result = durable.durable_session_run_executive(
        agent,
        "hello jarvis",
        control=control,
        session_id="cli-1",
    )

    assert result["message"] == "ok"
    assert seen == ["goal_current"]


def test_exact_real_vague_results_query_never_enters_global_history(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    control = _Control([_goal("goal_db41040b0ebe", "cli-live", "2026-08-23T00:14:49+05:30")])

    class Brain:
        @staticmethod
        def status(goal_id: str):
            assert goal_id == "goal_db41040b0ebe"
            return {
                "goal": {"id": goal_id, "title": "Street Fighter-like game", "state": "assigned"},
                "state": "queued",
                "states": {"assigned": 1},
                "tasks": [{"id": "task_builder", "title": "Implement the objective", "state": "assigned"}],
                "active_tasks": [],
                "pending_approvals": [],
            }

    class Kernel:
        brain = Brain()

    monkeypatch.setattr(reliable, "_kernel_for", lambda agent, control: Kernel())
    monkeypatch.setattr(
        durable,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not enter global/history resolver")),
    )

    result = durable.durable_session_run_executive(
        agent,
        "what are the results of task i gave you",
        control=control,
        session_id="cli-live",
    )

    assert result["goal_id"] == "goal_db41040b0ebe"
    assert result["state"] == "queued"
    assert result["frontdoor"]["durable_session_bound_status"] is True
    assert "Street Fighter-like game" in result["message"]
    assert "No completed task result has been recorded yet" in result["message"]
    assert "controlled task evidence reviews" not in result["message"].lower()


def test_bound_status_failure_fails_closed_on_same_goal(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    control = _Control([_goal("goal_current", "cli-1", "2026-08-23T00:03:00+05:30")])

    class Brain:
        @staticmethod
        def status(goal_id: str):
            assert goal_id == "goal_current"
            raise RuntimeError("simulated durable status fault")

    class Kernel:
        brain = Brain()

    monkeypatch.setattr(reliable, "_kernel_for", lambda agent, control: Kernel())
    monkeypatch.setattr(
        durable,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fall back globally")),
    )

    result = durable.durable_session_run_executive(
        agent,
        "what are the results of task i gave you",
        control=control,
        session_id="cli-1",
    )

    assert result["goal_id"] == "goal_current"
    assert result["state"] == "status_unavailable"
    assert result["result"]["status_read_failed"] is True
    assert "did not substitute results from another mission" in result["message"]


def test_durable_lookup_never_crosses_cli_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _Agent()
    control = _Control(
        [
            _goal("goal_a", "cli-a", "2026-08-23T00:03:00+05:30"),
            _goal("goal_b", "cli-b", "2026-08-23T00:04:00+05:30"),
        ]
    )

    seen: list[str] = []

    def previous(self, user_input: str, **kwargs):
        session_id = kwargs["session_id"]
        seen.append(reliable._session_bindings(self).get(session_id, ""))
        return {"intent": "conversation", "message": "ok", "result": {}}

    monkeypatch.setattr(durable, "_PREVIOUS_RUN_EXECUTIVE", previous)

    durable.durable_session_run_executive(agent, "hello", control=control, session_id="cli-a")
    durable.durable_session_run_executive(agent, "hello", control=control, session_id="cli-b")

    assert seen == ["goal_a", "goal_b"]
