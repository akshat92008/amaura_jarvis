from __future__ import annotations

import os

import pytest

from jarvis.amaura import review_diversity
from jarvis.amaura.models import GovernanceError, TaskState


class _Store:
    def __init__(self) -> None:
        self.state = TaskState.AWAITING_REVIEW.value

    def get_work_item(self, task_id: str):
        return {"id": task_id, "state": self.state, "evidence": []}


class _Control:
    def __init__(self) -> None:
        self.store = _Store()


def _configure_omniroute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "test-key")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "auto/best-reasoning")
    monkeypatch.delenv("NVIDIA_REVIEW_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def test_auto_review_retries_actual_model_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_MAX_ATTEMPTS", "2")
    runner = review_diversity.DiverseGovernedReviewRunner(_Control())
    monkeypatch.setattr(
        runner,
        "_worker_models_from_evidence",
        lambda task: {"meta/llama-3.3-70b-instruct"},
    )

    calls: list[tuple[str, str]] = []

    def fake_base_run(self, task_id: str):
        calls.append(
            (
                os.environ.get("AMAURA_REVIEW_MODE", ""),
                os.environ.get("AMAURA_OMNIROUTE_REVIEW_MODEL", ""),
            )
        )
        if len(calls) == 1:
            raise GovernanceError(
                "Actual reviewer model must differ from every worker model used for the task"
            )
        return {"task_id": task_id, "state": TaskState.COMPLETED.value}

    monkeypatch.setattr(review_diversity._BASE_REVIEW_RUNNER, "run", fake_base_run)

    result = runner.run("task-1")

    assert result["state"] == TaskState.COMPLETED.value
    assert calls == [
        ("omniroute", "auto/best-reasoning"),
        ("omniroute", "z-ai/glm-5.2"),
    ]
    assert os.environ["AMAURA_REVIEW_MODE"] == "auto"
    assert os.environ["AMAURA_OMNIROUTE_REVIEW_MODEL"] == "auto/best-reasoning"


def test_explicit_review_mode_is_never_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "omniroute")
    runner = review_diversity.DiverseGovernedReviewRunner(_Control())
    monkeypatch.setattr(
        runner,
        "_worker_models_from_evidence",
        lambda task: {"meta/llama-3.3-70b-instruct"},
    )
    calls = 0

    def fake_base_run(self, task_id: str):
        nonlocal calls
        calls += 1
        raise GovernanceError(
            "Actual reviewer model must differ from every worker model used for the task"
        )

    monkeypatch.setattr(review_diversity._BASE_REVIEW_RUNNER, "run", fake_base_run)

    with pytest.raises(GovernanceError, match="Actual reviewer model must differ"):
        runner.run("task-1")

    assert calls == 1
    assert os.environ["AMAURA_REVIEW_MODE"] == "omniroute"


def test_auto_review_can_cross_to_distinct_hosted_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_MAX_ATTEMPTS", "3")

    attempts = review_diversity._review_attempts({"meta/llama-3.3-70b-instruct"})

    assert attempts == [
        ("omniroute", "auto/best-reasoning"),
        ("omniroute", "z-ai/glm-5.2"),
        ("cloud", "z-ai/glm-5.2"),
    ]
    assert all(provider != "local" for provider, _ in attempts)


def test_auto_review_fails_closed_when_all_distinct_routes_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_MAX_ATTEMPTS", "2")
    runner = review_diversity.DiverseGovernedReviewRunner(_Control())
    monkeypatch.setattr(
        runner,
        "_worker_models_from_evidence",
        lambda task: {"meta/llama-3.3-70b-instruct"},
    )
    calls = 0

    def fake_base_run(self, task_id: str):
        nonlocal calls
        calls += 1
        raise GovernanceError(
            "Actual reviewer model must differ from every worker model used for the task"
        )

    monkeypatch.setattr(review_diversity._BASE_REVIEW_RUNNER, "run", fake_base_run)

    with pytest.raises(GovernanceError, match="exhausted distinct hosted reviewer routes"):
        runner.run("task-1")

    assert calls == 2
    assert runner.control.store.state == TaskState.AWAITING_REVIEW.value


def test_auto_review_requires_hosted_distinct_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.delenv("AMAURA_OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("AMAURA_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_REVIEW_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    runner = review_diversity.DiverseGovernedReviewRunner(_Control())
    monkeypatch.setattr(
        runner,
        "_worker_models_from_evidence",
        lambda task: {"meta/llama-3.3-70b-instruct"},
    )

    with pytest.raises(GovernanceError, match="no distinct hosted reviewer route"):
        runner.run("task-1")
