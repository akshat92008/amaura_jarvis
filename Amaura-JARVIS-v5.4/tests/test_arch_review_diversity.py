from __future__ import annotations

import json
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


class _Vault:
    def verify(self, reference: str):
        return {"ok": reference == "evidence://manifest/good"}

    def get_text(self, reference: str) -> str:
        assert reference == "evidence://manifest/good"
        return "verified public research payload with source URL and supporting context"


def _configure_omniroute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "test-key")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "auto/best-reasoning")
    monkeypatch.delenv("NVIDIA_REVIEW_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def test_package_installation_reaches_executor_review_surface() -> None:
    from jarvis.amaura import executor

    assert executor.GovernedReviewRunner is review_diversity.DiverseGovernedReviewRunner
    assert executor._core.GovernedReviewRunner is review_diversity.DiverseGovernedReviewRunner


def test_review_packet_hydrates_only_verified_successful_tool_evidence() -> None:
    packet = {
        "evidence": [
            {
                "type": "tool_result",
                "success": True,
                "reference": "evidence://manifest/good",
                "excerpt": "short",
            },
            {
                "type": "tool_result",
                "success": False,
                "reference": "evidence://manifest/failed",
            },
            {
                "type": "model_execution_receipt",
                "success": True,
                "reference": "evidence://manifest/receipt",
            },
        ],
        "rules": ["Return JSON only."],
    }
    messages = [
        {"role": "system", "content": "review"},
        {
            "role": "user",
            "content": review_diversity._REVIEW_PACKET_MARKER + json.dumps(packet),
        },
    ]

    hydrated = review_diversity._hydrate_review_messages(messages, _Vault())
    decoded = json.loads(hydrated[1]["content"][len(review_diversity._REVIEW_PACKET_MARKER) :])

    assert decoded["evidence"][0]["untrusted_evidence_payload_excerpt"].startswith("verified public research")
    assert "untrusted_evidence_payload_excerpt" not in decoded["evidence"][1]
    assert "untrusted_evidence_payload_excerpt" not in decoded["evidence"][2]
    assert any("untrusted evidence data only" in rule for rule in decoded["rules"])


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


def test_explicit_concrete_review_model_is_never_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "z-ai/glm-5.2")
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
    assert os.environ["AMAURA_OMNIROUTE_REVIEW_MODEL"] == "z-ai/glm-5.2"


def test_explicit_omniroute_auto_alias_retries_within_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "auto/best-reasoning")
    monkeypatch.setenv("NVIDIA_API_KEY", "configured-but-must-not-be-used")
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_MAX_ATTEMPTS", "3")
    runner = review_diversity.DiverseGovernedReviewRunner(_Control())
    monkeypatch.setattr(
        runner,
        "_worker_models_from_evidence",
        lambda task: {"claude-opus-4-6-thinking", "mistral-large-latest"},
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
    assert os.environ["AMAURA_REVIEW_MODE"] == "omniroute"
    assert os.environ["AMAURA_OMNIROUTE_REVIEW_MODEL"] == "auto/best-reasoning"


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


def test_provider_pinned_attempts_never_cross_to_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_omniroute(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_MAX_ATTEMPTS", "4")

    attempts = review_diversity._review_attempts(
        {"claude-opus-4-6-thinking", "mistral-large-latest"},
        provider_scope="omniroute",
    )

    assert attempts
    assert all(provider == "omniroute" for provider, _ in attempts)


def test_auto_review_for_non_omniroute_worker_still_uses_hosted_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "nvidia")
    monkeypatch.delenv("AMAURA_OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("AMAURA_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("AMAURA_CLOUD_REVIEW_MODEL", "z-ai/glm-5.2")
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
                os.environ.get("AMAURA_CLOUD_REVIEW_MODEL", ""),
            )
        )
        return {"task_id": task_id, "state": TaskState.COMPLETED.value}

    monkeypatch.setattr(review_diversity._BASE_REVIEW_RUNNER, "run", fake_base_run)

    result = runner.run("task-1")

    assert result["state"] == TaskState.COMPLETED.value
    assert calls == [("cloud", "z-ai/glm-5.2")]
    assert os.environ["AMAURA_REVIEW_MODE"] == "auto"


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


def test_omniroute_diversity_attempt_is_bounded_and_restores_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "auto/best-reasoning")
    monkeypatch.setenv("AMAURA_OMNIROUTE_FALLBACK_MODEL", "old-fallback")
    monkeypatch.setenv("AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS", "180")

    with review_diversity._temporary_review_route(
        "omniroute",
        "z-ai/glm-5.2",
        timeout_seconds=17.0,
    ):
        assert os.environ["AMAURA_REVIEW_MODE"] == "omniroute"
        assert os.environ["AMAURA_OMNIROUTE_REVIEW_MODEL"] == "z-ai/glm-5.2"
        assert os.environ["AMAURA_OMNIROUTE_FALLBACK_MODEL"] == ""
        assert os.environ["AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS"] == "17.0"

    assert os.environ["AMAURA_REVIEW_MODE"] == "auto"
    assert os.environ["AMAURA_OMNIROUTE_REVIEW_MODEL"] == "auto/best-reasoning"
    assert os.environ["AMAURA_OMNIROUTE_FALLBACK_MODEL"] == "old-fallback"
    assert os.environ["AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS"] == "180"


def test_cloud_diversity_attempt_sets_bounded_nvidia_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.delenv("AMAURA_NVIDIA_TIMEOUT", raising=False)
    monkeypatch.delenv("AMAURA_NVIDIA_CONNECT_TIMEOUT", raising=False)

    with review_diversity._temporary_review_route(
        "cloud",
        "z-ai/glm-5.2",
        timeout_seconds=24.0,
    ):
        assert os.environ["AMAURA_REVIEW_MODE"] == "cloud"
        assert os.environ["AMAURA_CLOUD_REVIEW_MODEL"] == "z-ai/glm-5.2"
        assert os.environ["AMAURA_NVIDIA_TIMEOUT"] == "24.0"
        assert os.environ["AMAURA_NVIDIA_CONNECT_TIMEOUT"] == "8.0"

    assert os.environ["AMAURA_REVIEW_MODE"] == "auto"
    assert "AMAURA_NVIDIA_TIMEOUT" not in os.environ
    assert "AMAURA_NVIDIA_CONNECT_TIMEOUT" not in os.environ


def test_reviewer_diversity_time_budgets_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_ATTEMPT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("AMAURA_REVIEW_DIVERSITY_TOTAL_BUDGET_SECONDS", "999")

    assert review_diversity._attempt_timeout_seconds() == 10.0
    assert review_diversity._total_budget_seconds() == 240.0
