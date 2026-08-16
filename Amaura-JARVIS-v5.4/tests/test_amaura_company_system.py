from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from jarvis.amaura.company import DEPARTMENT_MISSIONS, company_blueprint
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.handoffs import create_antigravity_packet, create_flow_packet
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.registry import ALL_AGENTS
from jarvis.amaura.resources import CapabilityRouter
from jarvis.amaura.workflows import WORKFLOWS
from jarvis.tools.registry import ALL_TOOL_DEFINITIONS


def test_complete_company_registry_and_workflow_catalogue():
    assert len(ALL_AGENTS) == 57
    assert len({agent.agent_id for agent in ALL_AGENTS}) == 57
    assert len(WORKFLOWS) == 22
    assert {
        "company_operating_review",
        "product_discovery",
        "incident_response",
    }.issubset(WORKFLOWS)
    departments = Counter(agent.department for agent in ALL_AGENTS)
    assert set(departments).issubset(DEPARTMENT_MISSIONS)
    assert {
        "strategy",
        "product",
        "operations",
        "finance",
        "security_legal",
        "customer_success",
        "community",
        "ventures",
    }.issubset(departments)


def test_tool_schemas_are_unique_and_match_employee_contracts():
    names = [definition["function"]["name"] for definition in ALL_TOOL_DEFINITIONS]
    assert len(names) == len(set(names))
    declared = set(names)
    assert {tool for agent in ALL_AGENTS for tool in agent.tools}.issubset(declared)


def test_company_blueprint_is_actionable_and_mac_aware():
    blueprint = company_blueprint()
    assert blueprint["employee_count"] == 57
    assert blueprint["workflow_count"] == 22
    assert blueprint["resource_profile"]["strategy"] == "control-plane-local-heavy-work-on-demand"
    assert blueprint["autonomy_boundary"]["founder_only"]
    assert all(department["employee_count"] > 0 for department in blueprint["departments"])


def test_free_first_router_prefers_builtin_and_can_select_nvidia():
    router = CapabilityRouter()
    route = router.route("orchestration")
    assert route.provider_key == "amaura_builtin"
    assert route.tier == "builtin"

    with patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}, clear=False):
        cloud = router.route("cloud_llm")
    assert cloud.provider_key == "nvidia_api"
    assert cloud.tier == "free_api"


def test_subscription_resources_are_never_silently_selected():
    router = CapabilityRouter()
    with patch.dict("os.environ", {"AMAURA_ANTIGRAVITY_ENABLED": "1"}, clear=False):
        with pytest.raises(GovernanceError):
            router.route("senior_coding", allow_subscription=False)
        route = router.route("senior_coding", allow_subscription=True)
    assert route.provider_key == "antigravity"
    assert route.mode == "manual_handoff"


def test_founder_handoffs_are_content_addressed_and_do_not_execute(monkeypatch):
    with TemporaryDirectory() as temp:
        root = Path(temp)
        repo = root / "repo"
        repo.mkdir()
        monkeypatch.setenv("AMAURA_DATA_DIR", str(root / "data"))
        first = create_antigravity_packet(
            objective="Implement verified feature",
            repository=str(repo),
            plan=["Read the approved spec", "Implement only inside the repository", "Run tests"],
            acceptance_criteria=["Tests pass", "Diff contains no credentials"],
        )
        second = create_antigravity_packet(
            objective="Implement verified feature",
            repository=str(repo),
            plan=["Read the approved spec", "Implement only inside the repository", "Run tests"],
            acceptance_criteria=["Tests pass", "Diff contains no credentials"],
        )
        assert first.payload_sha256 == second.payload_sha256
        assert Path(first.json_path).exists()
        payload = json.loads(Path(first.json_path).read_text())
        assert payload["requires_founder_action"] is True
        assert payload["context"]["repository"] == str(repo.resolve())


def test_flow_handoff_requires_scene_prompts_and_stays_private(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_DATA_DIR", temp)
        packet = create_flow_packet(
            objective="Produce one approved Amaura launch scene",
            scenes=[{"prompt": "An abstract blue network forming over a map of India", "duration_seconds": 8}],
            acceptance_criteria=["No logos", "No public upload", "16:9 clip returned for QA"],
        )
        payload = json.loads(Path(packet.json_path).read_text())
        assert payload["provider"] == "google-flow"
        assert payload["requires_founder_action"] is True
        assert payload["context"]["scenes"][0]["duration_seconds"] == 8


def test_new_company_workflows_instantiate_in_durable_control_plane(monkeypatch):
    with TemporaryDirectory() as temp:
        monkeypatch.setenv("AMAURA_DATA_DIR", temp)
        monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(Path(temp) / "evidence"))
        control = AmauraControlPlane()
        try:
            review = control.create_program(
                objective="Run the weekly operating review",
                success_metric="Founder receives evidenced priorities",
                workflow_key="company_operating_review",
                inputs={"review_window": "2026-W32"},
            )
            discovery = control.create_program(
                objective="Validate an affordable AI developer tool",
                success_metric="Build or kill decision backed by evidence",
                workflow_key="product_discovery",
                inputs={"problem_space": "AI coding", "target_user": "Indian students"},
            )
            assert len(review["tasks"]) == 5
            assert len(discovery["tasks"]) == 4
            assert review["tasks"][0]["owner_id"] == "operations_manager"
            assert discovery["tasks"][0]["owner_id"] == "product_discovery"
        finally:
            control.close()


def test_legacy_fable_executor_rejects_workspace_escape_and_shell_chaining(tmp_path):
    from jarvis.fable_engine import WorkspaceExecutor

    executor = WorkspaceExecutor(str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        executor.write_file("../outside.txt", "blocked")
    result = executor.run_command("python3 -c 'print(1)' && touch outside.txt")
    assert result["success"] is False
    assert "Shell operators" in result["stderr"]
    assert not (tmp_path / "outside.txt").exists()


def test_legacy_fable_dashboard_is_disabled_by_default(monkeypatch):
    from jarvis.fable_engine import run_fable_dashboard

    monkeypatch.delenv("FABLE_SERVER_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        run_fable_dashboard()


def test_incident_response_workflow_policy_validation(tmp_path):
    db_path = tmp_path / "test.db"
    control = AmauraControlPlane(db_path=db_path)
    try:
        prog = control.create_program(
            objective="Contain and recover from suspected credentials leak",
            success_metric="Incident contained, patch applied, verified",
            workflow_key="incident_response",
            inputs={"incident_summary": "API key leak in dev logs", "repository_path": str(tmp_path)},
        )
        assert len(prog["tasks"]) == 4
        assert prog["tasks"][0]["metadata"]["step_key"] == "triage"
        assert prog["tasks"][1]["metadata"]["step_key"] == "contain"
        assert prog["tasks"][1]["owner_id"] == "security_director"
        assert prog["tasks"][1]["risk"] == "medium"
        assert prog["tasks"][2]["metadata"]["step_key"] == "root_cause"
        assert prog["tasks"][2]["owner_id"] == "patch_engineer"
        assert prog["tasks"][2]["risk"] == "medium"
    finally:
        control.close()


def test_policy_engine_rejects_unauthorized_risk_assignment():
    from jarvis.amaura.models import RiskLevel
    from jarvis.amaura.policy import PolicyEngine
    from jarvis.amaura.registry import get_agent

    qa_agent = get_agent("qa")
    assert qa_agent.max_risk == RiskLevel.LOW

    unauthorized_task = {
        "id": "task_1",
        "owner_id": "qa",
        "risk": "medium",
        "budget_cents": 100,
        "reviewer_id": "jarvis",
    }
    decision = PolicyEngine.validate_assignment(unauthorized_task)
    assert decision.allowed is False
    assert any("may not own medium-risk work" in r for r in decision.reasons)
