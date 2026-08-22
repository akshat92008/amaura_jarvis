from __future__ import annotations

from types import SimpleNamespace

import pytest

import jarvis.amaura.runtime_guards as guards


@pytest.mark.parametrize(
    "reason",
    [
        "Command failed independent verification: 'pytest': 1 failed",
        "Antigravity changed-file manifest does not match Git: declared=[] actual=['app.py']",
        "Independent verification mutated the repository; engineering result rejected",
    ],
)
def test_independent_verification_failure_markers_are_terminal(reason: str) -> None:
    assert guards.is_independent_verification_failure(reason) is True


@pytest.mark.parametrize(
    "reason",
    [
        "OmniRoute request failed [PROVIDER_TIMEOUT] for model x",
        "Antigravity delivery exceeded its approved timeout",
        "temporary network failure",
        "Capability operation is temporarily unavailable",
    ],
)
def test_transient_or_worker_failures_are_not_reclassified(reason: str) -> None:
    assert guards.is_independent_verification_failure(reason) is False


class _FakeStore:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []

    def get_work_item(self, task_id: str):
        return {"id": task_id, "state": "blocked", "metadata": {"existing": True}}

    def update_work_item(self, task_id: str, **fields):
        self.updated.append((task_id, fields))
        return {"id": task_id, **fields}

    def publish_event(self, *args, **kwargs):
        return None

    def audit(self, *args, **kwargs):
        return None


class _FakeControl:
    def __init__(self) -> None:
        self.store = _FakeStore()


class _FakeRunner:
    def __init__(self) -> None:
        self.control = _FakeControl()


def test_verifier_failure_becomes_nonretryable_without_second_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_original(self, task_id: str, max_iterations: int = 12):
        nonlocal calls
        calls += 1
        return {
            "status": "blocked",
            "task_id": task_id,
            "reason": "Command failed independent verification: 'pytest': 1 failed",
            "retryable": True,
        }

    monkeypatch.setattr(guards, "_ORIGINAL_RUN", fake_original)
    runner = _FakeRunner()

    result = guards.guarded_task_run(runner, "task_example")

    assert calls == 1
    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert result["verification_failure"] is True
    assert len(runner.control.store.updated) == 1
    task_id, fields = runner.control.store.updated[0]
    assert task_id == "task_example"
    assert fields["state"] == "failed"
    assert fields["metadata"]["retryable"] is False
    assert fields["metadata"]["execution_retry_suppressed"] is True


def test_transient_blocked_failure_keeps_existing_retry_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_original(self, task_id: str, max_iterations: int = 12):
        nonlocal calls
        calls += 1
        return {
            "status": "blocked",
            "task_id": task_id,
            "reason": "OmniRoute request failed [PROVIDER_TIMEOUT] for model x",
            "retryable": True,
        }

    monkeypatch.setattr(guards, "_ORIGINAL_RUN", fake_original)
    runner = _FakeRunner()

    result = guards.guarded_task_run(runner, "task_example")

    assert calls == 1
    assert result["status"] == "blocked"
    assert result["retryable"] is True
    assert runner.control.store.updated == []
