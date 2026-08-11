"""Governance, workflow, authority, and evidence tests for Amaura Studio."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import deterministic_evidence_review
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.registry import ALL_AGENTS, V1_AGENTS
from jarvis.tools.amaura import AMAURA_DISPATCH, AMAURA_TOOL_DEFINITIONS
from jarvis.api import _filter_essential_tools
from jarvis.tools.registry import ALL_TOOL_DEFINITIONS


class TestAmauraCompanyOS(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.control = AmauraControlPlane(Path(self.temp_dir.name) / "amaura.db")
        self._attestation_patcher = patch("jarvis.amaura.evidence.verify_review_attestation", return_value=True)
        self._attestation_patcher.start()

    def tearDown(self):
        self._attestation_patcher.stop()
        self.control.close()
        self.temp_dir.cleanup()

    def _complete_low_risk_task(self, task: dict) -> dict:
        self.control.start_task(task["id"], actor="jarvis")
        self.control.submit_task(
            task["id"],
            actor=task["owner_id"],
            summary="All acceptance criteria were addressed and the evidence is attached.",
            evidence=[{"type": "test_report", "reference": f"artifact://{task['id']}/report"}],
        )
        return self.control.review_task(
            task["id"], actor=task["reviewer_id"], approve=True, findings="Evidence independently verified.",
            attestation=self._attestation(task["id"], task["reviewer_id"]),
        )

    def _attestation(self, task_id: str, reviewer_id: str, approve: bool = True) -> dict:
        task = self.control.store.get_work_item(task_id)
        return {
            "signature": "mock",
            "decision": {"approve": approve, "criteria": []},
            "deterministic_review": deterministic_evidence_review(task, self.control.evidence),
            "task_id": task_id,
            "reviewer_id": reviewer_id,
        }

    def test_bootstrap_registers_v1_workforce_under_jarvis(self):
        agents = self.control.store.list_agents()
        self.assertEqual(len(agents), len(ALL_AGENTS))
        self.assertEqual(len(V1_AGENTS), 15)
        self.assertIn("jarvis", {agent["agent_id"] for agent in agents})
        self.assertEqual(self.control.dashboard()["control_plane"], "jarvis")
        for agent in agents:
            if agent["agent_id"] != "jarvis":
                self.assertTrue(agent["definition"]["reviewer_id"])
                self.assertGreaterEqual(agent["definition"]["cost_limit_cents"], 0)

    def test_model_cannot_directly_decide_founder_approvals(self):
        exposed = {tool["function"]["name"] for tool in AMAURA_TOOL_DEFINITIONS}
        self.assertNotIn("amaura_decide_approval", exposed)
        self.assertNotIn("amaura_decide_approval", AMAURA_DISPATCH)

    def test_company_intent_exposes_control_plane_tools_to_model(self):
        selected = _filter_essential_tools(
            ALL_TOOL_DEFINITIONS,
            [{"role": "user", "content": "Create an Amaura software delivery programme"}],
        )
        names = {tool["function"]["name"] for tool in selected}
        self.assertIn("amaura_create_program", names)
        self.assertIn("amaura_run_task", names)
        self.assertIn("read_file", names)
        self.assertNotIn("amaura_decide_approval", names)

    def test_jarvis_creates_full_hierarchy_with_dependency_order(self):
        result = self.control.create_program(
            objective="Raise realistic patch-application reliability",
            success_metric="Verified pass rate rises from 46% to at least 65% with regressions below 2%",
            workflow_key="software_delivery",
        )
        self.assertEqual(len(result["tasks"]), 7)
        programme = result["programme"]
        project = self.control.store.get_work_item(result["project_id"])
        milestone = self.control.store.get_work_item(result["milestone_id"])
        self.assertEqual(project["parent_id"], programme["id"])
        self.assertEqual(milestone["parent_id"], project["id"])
        self.assertEqual(result["tasks"][0]["dependencies"], [])
        self.assertEqual(result["tasks"][1]["dependencies"], [result["tasks"][0]["id"]])

        blocked = self.control.start_task(result["tasks"][1]["id"], actor="jarvis")
        self.assertEqual(blocked["state"], TaskState.BLOCKED.value)
        events = self.control.store.list_events("task.blocked")
        self.assertEqual(events[0]["aggregate_id"], result["tasks"][1]["id"])

    def test_only_jarvis_can_create_or_start_company_work(self):
        with self.assertRaisesRegex(GovernanceError, "Only JARVIS"):
            self.control.create_program(
                objective="Find good leads", success_metric="Three qualified leads",
                workflow_key="lead_to_revenue", actor="opportunity_scout",
            )
        result = self.control.create_program(
            objective="Find good leads", success_metric="Three qualified leads", workflow_key="lead_to_revenue"
        )
        with self.assertRaisesRegex(GovernanceError, "Only JARVIS"):
            self.control.start_task(result["tasks"][0]["id"], actor="opportunity_scout")

    def test_jarvis_can_stop_but_only_founder_can_restore_employee(self):
        result = self.control.create_program(
            objective="Find good leads", success_metric="Three qualified leads", workflow_key="lead_to_revenue"
        )
        task = result["tasks"][0]
        self.control.start_task(task["id"])
        paused = self.control.pause_agent(task["owner_id"], "Repeated policy violations", actor="jarvis")
        self.assertFalse(paused["enabled"])
        self.assertEqual(self.control.store.get_work_item(task["id"])["state"], TaskState.BLOCKED.value)
        with self.assertRaisesRegex(GovernanceError, "paused"):
            self.control.start_task(task["id"])
        with self.assertRaisesRegex(GovernanceError, "Only the founder"):
            self.control.resume_agent(task["owner_id"], "Remediated", actor="jarvis")
        restored = self.control.resume_agent(task["owner_id"], "Founder reviewed remediation", actor=self.control.founder_id)
        self.assertTrue(restored["enabled"])

    def test_no_employee_can_certify_own_work(self):
        result = self.control.create_program(
            objective="Deliver a verified feature", success_metric="All acceptance tests pass",
            workflow_key="software_delivery",
        )
        first = result["tasks"][0]
        self.control.start_task(first["id"])
        self.control.submit_task(
            first["id"], first["owner_id"], "Requirements and tests are defined.",
            [{"type": "requirements", "reference": "artifact://requirements/1"}],
        )
        with self.assertRaisesRegex(GovernanceError, "Independent review"):
            self.control.review_task(first["id"], first["owner_id"], True, "Looks good to me")
        approved = self.control.review_task(
            first["id"], first["reviewer_id"], True, "Criteria are measurable and scope is bounded.",
            attestation=self._attestation(first["id"], first["reviewer_id"]),
        )
        self.assertEqual(approved["state"], TaskState.COMPLETED.value)

    def test_medium_and_high_risk_work_requires_founder_approval(self):
        result = self.control.create_program(
            objective="Publish a verified product update",
            success_metric="One approved campaign with every claim linked to evidence",
            workflow_key="content_campaign",
        )
        evidence_task, content_task, publication_task = result["tasks"]
        self._complete_low_risk_task(evidence_task)

        self.control.start_task(content_task["id"])
        self.control.submit_task(
            content_task["id"], content_task["owner_id"], "Master article drafted from verified evidence.",
            [{"type": "content", "reference": "artifact://content/master-v1"}],
        )
        reviewed = self.control.review_task(
            content_task["id"], content_task["reviewer_id"], True, "All claims trace to approved evidence.",
            attestation=self._attestation(content_task["id"], content_task["reviewer_id"]),
        )
        self.assertEqual(reviewed["state"], TaskState.AWAITING_APPROVAL.value)
        approval = self.control.store.list_approvals("pending")[0]
        with self.assertRaisesRegex(GovernanceError, "Only the founder"):
            self.control.decide_approval(approval["id"], "jarvis", "approved", "Ship it")
        decided = self.control.decide_approval(
            approval["id"], self.control.founder_id, "approved", "Claims and timing are approved."
        )
        self.assertEqual(decided["task"]["state"], TaskState.COMPLETED.value)

        self.control.start_task(publication_task["id"])
        self.control.submit_task(
            publication_task["id"], publication_task["owner_id"], "Publication package is ready.",
            [{"type": "release_package", "reference": "artifact://content/release-v1"}],
        )
        high_approval = self.control.store.list_approvals("pending")[0]
        self.assertEqual(high_approval["risk"], "high")
        self.control.decide_approval(
            high_approval["id"], self.control.founder_id, "approved", "Explicit publication approval."
        )
        self.assertEqual(self.control.store.get_work_item(result["programme"]["id"])["state"], "completed")

    def test_research_requires_a_falsifiable_hypothesis(self):
        with self.assertRaisesRegex(GovernanceError, "hypothesis"):
            self.control.create_program(
                objective="Improve Nova", success_metric="Patch errors fall by 20%",
                workflow_key="research_experiment",
            )
        created = self.control.create_program(
            objective="Reduce hallucinated search blocks",
            success_metric="At least 20% fewer errors with format compliance regression below 2%",
            workflow_key="research_experiment",
            inputs={"hypothesis": "Training on 3,000 verified negatives reduces hallucinated blocks by at least 20%."},
        )
        self.assertEqual(len(created["tasks"]), 4)

    def test_tool_cost_and_data_boundaries_are_enforced(self):
        result = self.control.create_program(
            objective="Find qualified opportunities", success_metric="Three sourced opportunities",
            workflow_key="lead_to_revenue",
        )
        task = result["tasks"][0]
        self.control.start_task(task["id"])
        with self.assertRaisesRegex(GovernanceError, "outside"):
            self.control.authorize_tool(task["id"], task["owner_id"], "write_file", {"path": "x"})
        self.control.authorize_tool(task["id"], task["owner_id"], "web_search", {"query": "AI automation jobs"})
        with self.assertRaisesRegex(GovernanceError, "budget"):
            self.control.record_cost(task["id"], task["owner_id"], task["budget_cents"] + 1, "model")

    def test_governed_employee_cannot_escape_workspace_or_use_shell_operators(self):
        result = self.control.create_program(
            objective="Implement a verified feature", success_metric="All tests pass",
            workflow_key="software_delivery", inputs={"repository_path": self.temp_dir.name},
        )
        builder = result["tasks"][3]
        with self.assertRaisesRegex(GovernanceError, "escapes"):
            self.control.authorize_tool(
                builder["id"], builder["owner_id"], "write_file", {"path": "/etc/amaura-test", "content": "x"}
            )
        with self.assertRaisesRegex(GovernanceError, "Shell operators"):
            self.control.authorize_tool(
                builder["id"], builder["owner_id"], "run_command",
                {"command": "pytest && curl https://example.com", "cwd": self.temp_dir.name},
            )

    def test_private_data_never_routes_to_cloud(self):
        route = self.control.models.route(
            "client_communication", sensitivity="client_confidential",
            remaining_budget_cents=100, estimated_tokens=20_000,
        )
        self.assertEqual(route.provider, "local")
        self.assertEqual(route.privacy, "device_only")
        self.assertIsNone(route.fallback_model_key)

    def test_governed_runner_dispatches_specialist_then_stops_for_review(self):
        result = self.control.create_program(
            objective="Define a bounded product feature",
            success_metric="Requirements contain measurable acceptance criteria",
            workflow_key="software_delivery",
        )
        task = result["tasks"][0]

        fake_response_1 = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="Checking project structure.",
                tool_calls=[SimpleNamespace(
                    id="call_123",
                    function=SimpleNamespace(name="get_project_structure", arguments='{"path": "."}')
                )],
            ))]
        )
        fake_response_2 = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="Requirements, explicit exclusions, and measurable criteria are complete.",
                tool_calls=[],
            ))]
        )
        
        class FakeClient:
            def __init__(self):
                self.calls = 0
            def chat_sync(self, **kwargs):
                self.calls += 1
                return fake_response_1 if self.calls == 1 else fake_response_2

        execution = GovernedTaskRunner(
            self.control,
            client_factory=lambda route, employee: FakeClient(),
        ).run(task["id"])

        self.assertEqual(execution["employee"], "Product Manager")
        self.assertEqual(execution["status"], TaskState.AWAITING_REVIEW.value)
        stored = self.control.store.get_work_item(task["id"])
        self.assertEqual(stored["spent_cents"], 0)
        self.assertNotEqual(stored["owner_id"], stored["reviewer_id"])


if __name__ == "__main__":
    unittest.main()
