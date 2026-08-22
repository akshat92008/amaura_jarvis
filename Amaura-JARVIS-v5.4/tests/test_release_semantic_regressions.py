"""Deterministic guards for the live semantic-root execution repair path."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.models import TaskState


def test_tool_timeout_is_structured_and_bounded() -> None:
    runner = object.__new__(GovernedTaskRunner)

    def slow_tool(*_args: object, **_kwargs: object) -> str:
        time.sleep(2)
        return "unreachable"

    started = time.monotonic()
    result = json.loads(runner._execute_tool("slow_tool", {"timeout": 1}, slow_tool))

    assert time.monotonic() - started < 1.5
    assert result == {
        "ok": False,
        "data": {},
        "error": "Tool slow_tool timed out after 1s",
        "external_id": "",
        "retryable": True,
    }


def test_unhandled_execution_error_transitions_active_task_to_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = AmauraControlPlane(tmp_path / "qualification.db")
    try:
        programme = control.create_program(
            objective="Produce a bounded regression test",
            success_metric="A deterministic test is recorded",
            workflow_key="software_delivery",
        )
        task_id = programme["tasks"][0]["id"]
        control.start_task(task_id, actor="jarvis")
        runner = GovernedTaskRunner(control)

        def fail(_task_id: str, *, max_iterations: int) -> dict[str, object]:
            raise RuntimeError("simulated provider failure")

        monkeypatch.setattr(runner, "_run", fail)
        result = runner.run(task_id, max_iterations=3)
        stored = control.store.get_work_item(task_id)

        assert result["status"] == "blocked"
        assert stored["state"] == TaskState.BLOCKED.value
        assert stored["metadata"]["block_reason"] == "simulated provider failure"
        assert stored["metadata"]["retryable"] is True
        assert stored["metadata"]["last_iteration"] == 3
    finally:
        control.close()
