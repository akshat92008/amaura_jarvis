from __future__ import annotations

import pytest

import jarvis.exact_reference as exact


class _Agent:
    pass


class _Store:
    def __init__(self, items: dict[str, dict]):
        self.items = items

    def get_work_item(self, item_id: str) -> dict:
        if item_id not in self.items:
            raise KeyError(item_id)
        return self.items[item_id]


class _Control:
    def __init__(self, items: dict[str, dict]):
        self.store = _Store(items)


def _item(item_id: str, *, item_type: str = "programme", state: str = "assigned", summary: str = "") -> dict:
    return {
        "id": item_id,
        "item_type": item_type,
        "title": "Street Fighter build" if item_id.startswith("goal_") else "Implement the objective",
        "state": state,
        "summary": summary,
        "owner_id": "builder",
        "reviewer_id": "qa",
    }


def test_explicit_goal_status_never_calls_fuzzy_or_model_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    goal_id = "goal_8d5c7339aa87"
    control = _Control({goal_id: _item(goal_id)})

    class Brain:
        @staticmethod
        def status(requested: str):
            assert requested == goal_id
            return {
                "goal": {"id": goal_id, "title": "Street Fighter build", "state": "assigned"},
                "state": "queued",
                "states": {"assigned": 1},
                "tasks": [{"id": "task_game", "title": "Implement the objective", "summary": ""}],
                "active_tasks": [],
                "pending_approvals": [],
            }

    class Kernel:
        brain = Brain()

    monkeypatch.setattr("jarvis.reliable_cli._kernel_for", lambda agent, control: Kernel())
    monkeypatch.setattr(
        exact,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("explicit id must not reach fuzzy/model resolver")),
    )

    result = exact.exact_reference_run_executive(
        _Agent(),
        "goal_8d5c7339aa87 what are the results",
        control=control,
        session_id="cli-live",
    )

    assert result["goal_id"] == goal_id
    assert result["state"] == "queued"
    assert result["result"]["exact_lookup"] is True
    assert "Street Fighter build" in result["message"]
    assert "investor" not in result["message"].lower()


def test_nonexistent_explicit_goal_fails_closed_without_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        exact,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("missing explicit id must be terminal")),
    )

    result = exact.exact_reference_run_executive(
        _Agent(),
        "goal_doesnotexist give me results",
        control=_Control({}),
        session_id="cli-live",
    )

    assert result["state"] == "not_found"
    assert result["result"]["found"] is False
    assert result["result"]["work_item_id"] == "goal_doesnotexist"
    assert "did not substitute" in result["message"]


def test_explicit_task_reads_exact_store_row_not_other_history(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = "task_705167d6038b"
    task = _item(task_id, item_type="task", state="completed", summary="Built and verified the requested game")
    monkeypatch.setattr(
        exact,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("explicit task must not reach model resolver")),
    )

    result = exact.exact_reference_run_executive(
        _Agent(),
        f"show results for {task_id}",
        control=_Control({task_id: task}),
    )

    assert result["state"] == "completed"
    assert result["result"]["work_item"]["id"] == task_id
    assert "Built and verified" in result["message"]


def test_multiple_explicit_ids_are_ambiguous_and_never_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        exact,
        "_PREVIOUS_RUN_EXECUTIVE",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ambiguous ids must not reach model resolver")),
    )
    result = exact.exact_reference_run_executive(
        _Agent(),
        "compare results of goal_aaa111 and goal_bbb222",
        control=_Control({}),
    )
    assert result["state"] == "ambiguous_reference"
    assert result["result"]["work_item_ids"] == ["goal_aaa111", "goal_bbb222"]


def test_non_status_explicit_id_control_still_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def previous(self, user_input: str, **kwargs):
        seen.append(user_input)
        return {"intent": "mission_control", "message": "delegated", "result": {}}

    monkeypatch.setattr(exact, "_PREVIOUS_RUN_EXECUTIVE", previous)
    result = exact.exact_reference_run_executive(
        _Agent(),
        "cancel goal_abc123",
        control=_Control({}),
    )
    assert result["message"] == "delegated"
    assert seen == ["cancel goal_abc123"]
