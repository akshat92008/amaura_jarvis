from __future__ import annotations

import pytest

from jarvis.amaura.brain import GoalCompiler, GoalRequest
from jarvis.amaura.executor import _completion_text
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.review_routing import effective_review_mode, omniroute_review_route

_REPAIR_OBJECTIVE = (
    "Inspect the current workspace repository. A test is failing. Diagnose the proven root cause, "
    "use the authenticated Antigravity coding path to make the smallest safe repair, independently "
    "verify the result, preserve deterministic evidence of the Antigravity change and review, and "
    "leave the repository with only the necessary source modification. Do not weaken, delete, or alter the test."
)


def _repair_request(tmp_path) -> GoalRequest:
    return GoalRequest(
        objective=_REPAIR_OBJECTIVE,
        workspace=str(tmp_path),
        coding_backend="antigravity",
        autonomy="execute_until_approval",
    )


def test_antigravity_repository_repair_routes_to_repository_write(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "0")
    compiler = GoalCompiler()
    request = _repair_request(tmp_path)

    assert compiler.classify(request) == "software"

    plan = compiler.compile(request)

    assert plan.domain == "software"
    assert plan.planner == "deterministic-software"
    assert plan.coding_backend == "antigravity"
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.action_type == "repository_write"
    assert task.metadata["coding_backend"] == "antigravity"
    assert "Relevant automated tests pass" in task.acceptance_criteria
    assert "No known critical regression remains" in task.acceptance_criteria


def test_repository_repair_fails_closed_if_direct_plan_is_forced(tmp_path):
    compiler = GoalCompiler()
    request = _repair_request(tmp_path)

    with pytest.raises(GovernanceError, match="cannot use direct_action"):
        compiler._direct_action_plan(request, str(tmp_path))


def test_explicit_research_with_cli_workspace_is_not_misrouted_to_repository_work(tmp_path):
    compiler = GoalCompiler()
    request = GoalRequest(
        objective="Research one current AI developer-tool trend and produce an internal recommendation.",
        workspace=str(tmp_path),
        coding_backend="antigravity",
    )

    plan = compiler.compile(request)

    assert plan.domain == "research"
    assert plan.planner == "deterministic-research"
    assert all(task.action_type != "repository_write" for task in plan.tasks)


def test_structured_provider_completion_content_is_normalized() -> None:
    assert _completion_text([{"type": "text", "text": "first"}, {"text": {"value": "second"}}]) == "first\nsecond"


def test_non_engineering_direct_action_routing_is_preserved(tmp_path):
    compiler = GoalCompiler()
    request = GoalRequest(
        objective="Reply with exactly: ROUTING_OK",
        workspace=str(tmp_path),
        coding_backend="antigravity",
    )

    assert compiler.classify(request) == "direct_action"


@pytest.mark.parametrize(
    ("worker", "fallback", "reviewer", "review_fallback", "independent"),
    [
        ("model-A", "", "model-A", "", False),
        ("model-A", "model-B", "model-B", "", False),
        ("model-A", "", "auto/best-reasoning", "", False),
        ("model-A", "", "model-C", "", True),
        ("model-A", "model-B", "model-C", "model-B", False),
    ],
)
def test_omniroute_review_route_requires_explicit_distinct_models(
    worker, fallback, reviewer, review_fallback, independent
):
    route = omniroute_review_route(
        {
            "AMAURA_OMNIROUTE_MODEL": worker,
            "AMAURA_OMNIROUTE_FALLBACK_MODEL": fallback,
            "AMAURA_OMNIROUTE_REVIEW_MODEL": reviewer,
            "AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL": review_fallback,
        }
    )
    assert route["independent"] is independent


def test_auto_review_mode_matches_omniroute_executor_route():
    assert effective_review_mode({"AMAURA_REVIEW_MODE": "auto", "AMAURA_MODEL_PROVIDER": "omniroute"}) == "omniroute"
    assert effective_review_mode({"AMAURA_REVIEW_MODE": "auto", "AMAURA_MODEL_PROVIDER": "local"}) == "local"


def test_omniroute_readiness_does_not_overclaim_alias_independence(monkeypatch, tmp_path):
    from jarvis.amaura.control_plane import AmauraControlPlane
    from jarvis.amaura.readiness import production_readiness

    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_STRICT_REVIEW", "1")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "test-route-key")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_MODEL", "model-A")
    monkeypatch.delenv("AMAURA_OMNIROUTE_FALLBACK_MODEL", raising=False)
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "auto/best-reasoning")
    control = AmauraControlPlane(tmp_path / "readiness.db")
    try:
        report = production_readiness(control, live=False)
    finally:
        control.close()
    assert report["checks"]["distinct_reviewer_model"] is False
    assert report["checks"]["reviewer_route_independence"] is False
    assert "reviewer_route_independence" in report["blockers"]


def test_omniroute_readiness_accepts_explicit_distinct_route(monkeypatch, tmp_path):
    from jarvis.amaura.control_plane import AmauraControlPlane
    from jarvis.amaura.readiness import production_readiness

    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "auto")
    monkeypatch.setenv("AMAURA_STRICT_REVIEW", "1")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "test-route-key")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_MODEL", "model-A")
    monkeypatch.delenv("AMAURA_OMNIROUTE_FALLBACK_MODEL", raising=False)
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "model-C")
    monkeypatch.delenv("AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL", raising=False)
    control = AmauraControlPlane(tmp_path / "readiness.db")
    try:
        report = production_readiness(control, live=False)
    finally:
        control.close()
    assert report["checks"]["distinct_reviewer_model"] is True
    assert report["checks"]["reviewer_route_independence"] is True


def test_omniroute_reviewer_never_inherits_worker_fallback(monkeypatch, tmp_path):
    from jarvis.amaura.executor import GovernedReviewRunner

    monkeypatch.setenv("AMAURA_OMNIROUTE_FALLBACK_MODEL", "worker-fallback")
    runner = GovernedReviewRunner.__new__(GovernedReviewRunner)
    runner.client_factory = lambda route, reviewer: route
    route = runner._client(object(), provider="omniroute", model_key="reviewer-model")
    assert route["fallback_model"] == ""


def _awaiting_model_review_task(control, tmp_path):
    task = control.create_program(
        objective="Produce a bounded internal research note",
        success_metric="Evidence is independently reviewed",
        workflow_key="software_delivery",
        inputs={"repository_path": str(tmp_path)},
    )["tasks"][0]
    control.start_task(task["id"], actor="jarvis")
    evidence = control.evidence.put_text("verified evidence", source="test")
    receipt = control.evidence.put_json(
        {"actual_model": "worker-model", "models_used": ["worker-model"]}, source="test:worker-receipt"
    )
    control.submit_task(
        task["id"],
        actor=task["owner_id"],
        summary="Bounded work completed.",
        evidence=[
            {"type": "test_report", "reference": evidence.reference, "sha256": evidence.sha256, "success": True},
            {
                "type": "model_execution_receipt",
                "reference": receipt.reference,
                "sha256": receipt.sha256,
                "success": True,
            },
        ],
    )
    return task["id"]


def test_reviewer_fallback_collision_is_rejected_before_review_call(monkeypatch, tmp_path):
    from jarvis.amaura.control_plane import AmauraControlPlane
    from jarvis.amaura.executor import GovernedReviewRunner

    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "test-route-key")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "reviewer-model")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL", "worker-model")
    control = AmauraControlPlane(tmp_path / "review.db")
    try:
        task_id = _awaiting_model_review_task(control, tmp_path)
        called = False

        def factory(route, reviewer):
            nonlocal called
            called = True
            return object()

        with pytest.raises(GovernanceError, match="differ from every worker model"):
            GovernedReviewRunner(control, client_factory=factory).run(task_id)
        assert called is False
    finally:
        control.close()


def test_actual_reviewer_model_collision_is_rejected_after_response(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from jarvis.amaura.control_plane import AmauraControlPlane
    from jarvis.amaura.executor import GovernedReviewRunner

    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_REVIEW_MODE", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "test-route-key")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_REVIEW_MODEL", "reviewer-model")
    monkeypatch.delenv("AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL", raising=False)
    control = AmauraControlPlane(tmp_path / "review.db")
    try:
        task_id = _awaiting_model_review_task(control, tmp_path)

        class Client:
            last_execution_metadata = {"actual_provider": "omniroute", "actual_model": "worker-model"}

            def chat_sync(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

        with pytest.raises(GovernanceError, match="Actual reviewer model must differ"):
            GovernedReviewRunner(control, client_factory=lambda route, reviewer: Client()).run(task_id)
    finally:
        control.close()
