"""Durability, approval-integrity, and security tests for the workforce supervisor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import deterministic_evidence_review
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.policy import PolicyEngine
from jarvis.amaura.supervisor import AmauraSupervisor


class _SuccessfulRunner:
    def __init__(self, control: AmauraControlPlane):
        self.control = control

    def run(self, task_id: str) -> dict:
        task = self.control.store.get_work_item(task_id)
        submitted = self.control.submit_task(
            task_id,
            actor=task["owner_id"],
            summary="The bounded task completed with verifiable evidence.",
            evidence=[
                {
                    "type": "test_report",
                    "reference": f"artifact://{task_id}/report",
                    "success": True,
                }
            ],
        )
        return {"status": submitted["state"], "task_id": task_id}


class _SuccessfulReviewer:
    def __init__(self, control: AmauraControlPlane):
        self.control = control

    def run(self, task_id: str) -> dict:
        task = self.control.store.get_work_item(task_id)
        deterministic = deterministic_evidence_review(task, self.control.evidence)
        updated = self.control.review_task(
            task_id,
            actor=task["reviewer_id"],
            approve=True,
            findings="Every acceptance criterion is supported by the submitted report.",
            attestation={
                "signature": "mock",
                "decision": {"approve": True, "criteria": []},
                "deterministic_review": deterministic,
                "task_id": task_id,
                "reviewer_id": task["reviewer_id"],
            },
        )
        return {"task_id": task_id, "approve": True, "state": updated["state"]}


class _TransientFailureRunner:
    def __init__(self, control: AmauraControlPlane):
        self.control = control

    def run(self, task_id: str) -> dict:
        raise ConnectionError("Local inference connection temporarily unavailable")


class TestAmauraSupervisor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.control = AmauraControlPlane(Path(self.temp_dir.name) / "amaura.db")
        self._attestation_patcher = patch("jarvis.amaura.evidence.verify_review_attestation", return_value=True)
        self._attestation_patcher.start()

    def tearDown(self):
        self._attestation_patcher.stop()
        self.control.close()
        self.temp_dir.cleanup()

    def _programme(self):
        return self.control.create_program(
            objective="Deliver a verified internal feature",
            success_metric="Every acceptance criterion passes independent review",
            workflow_key="software_delivery",
            inputs={"repository_path": self.temp_dir.name},
        )

    def _attestation(self, task_id: str, reviewer_id: str) -> dict:
        task = self.control.store.get_work_item(task_id)
        return {
            "signature": "mock",
            "decision": {"approve": True, "criteria": []},
            "deterministic_review": deterministic_evidence_review(task, self.control.evidence),
            "task_id": task_id,
            "reviewer_id": reviewer_id,
        }

    def test_supervisor_leases_executes_and_reviews_independently(self):
        programme = self._programme()
        first = programme["tasks"][0]
        supervisor = AmauraSupervisor(
            self.control,
            worker_id="test-worker",
            runner_factory=_SuccessfulRunner,
            reviewer_factory=_SuccessfulReviewer,
        )

        executed = supervisor.tick()
        self.assertEqual(executed["status"], "executed")
        self.assertEqual(executed["execution"]["state"], "succeeded")
        self.assertEqual(
            self.control.store.get_work_item(first["id"])["state"],
            TaskState.AWAITING_REVIEW.value,
        )

        reviewed = supervisor.tick()
        self.assertEqual(reviewed["status"], "reviewed")
        self.assertEqual(
            self.control.store.get_work_item(first["id"])["state"],
            TaskState.COMPLETED.value,
        )
        self.assertEqual(self.control.store.execution_status()["counts"]["succeeded"], 1)

    def test_transient_failures_retry_once_then_fail_closed(self):
        first = self._programme()["tasks"][0]
        supervisor = AmauraSupervisor(
            self.control,
            worker_id="retry-worker",
            max_attempts=2,
            runner_factory=_TransientFailureRunner,
            automatic_reviews=False,
        )

        retry = supervisor.tick()
        self.assertEqual(retry["status"], "retry_scheduled")
        self.assertEqual(
            self.control.store.get_work_item(first["id"])["state"],
            TaskState.ASSIGNED.value,
        )

        failed = supervisor.tick()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            self.control.store.get_work_item(first["id"])["state"],
            TaskState.FAILED.value,
        )
        self.assertEqual(len(self.control.store.list_executions(task_id=first["id"])), 2)

    def test_expired_worker_lease_is_recovered(self):
        first = self._programme()["tasks"][0]
        claim = self.control.store.claim_next_task(
            worker_id="crashed-worker",
            lease_seconds=30,
            max_attempts=2,
        )
        self.assertIsNotNone(claim)
        with self.control.store._lock:
            self.control.store._connection.execute(
                "UPDATE execution_runs SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
                (claim["run"]["id"],),
            )
            self.control.store._connection.commit()

        recovered = self.control.store.recover_expired_executions(max_attempts=2)
        self.assertEqual(recovered[0]["task_id"], first["id"])
        self.assertTrue(recovered[0]["retry_scheduled"])
        self.assertEqual(
            self.control.store.get_work_item(first["id"])["state"],
            TaskState.ASSIGNED.value,
        )

    def test_approval_is_bound_to_exact_payload(self):
        programme = self.control.create_program(
            objective="Publish a verified update",
            success_metric="Every public claim is independently evidenced",
            workflow_key="content_campaign",
        )
        evidence_task, content_task, _ = programme["tasks"]
        for task in (evidence_task,):
            self.control.start_task(task["id"])
            self.control.submit_task(
                task["id"],
                task["owner_id"],
                "Evidence register is complete.",
                [{"type": "evidence", "reference": "artifact://evidence/v1"}],
            )
            self.control.review_task(
                task["id"],
                task["reviewer_id"],
                True,
                "Evidence sources verified.",
                attestation=self._attestation(task["id"], task["reviewer_id"]),
            )
        self.control.start_task(content_task["id"])
        self.control.submit_task(
            content_task["id"],
            content_task["owner_id"],
            "Approved draft v1.",
            [{"type": "content", "reference": "artifact://content/v1"}],
        )
        self.control.review_task(
            content_task["id"],
            content_task["reviewer_id"],
            True,
            "Claims verified.",
            attestation=self._attestation(content_task["id"], content_task["reviewer_id"]),
        )
        approval = self.control.store.list_approvals("pending")[0]
        self.control.store.update_work_item(content_task["id"], summary="Tampered draft v2")

        with self.assertRaisesRegex(GovernanceError, "payload changed"):
            self.control.decide_approval(
                approval["id"],
                self.control.founder_id,
                "approved",
                "Approve the reviewed version.",
            )

    def test_audit_chain_detects_database_tampering(self):
        self._programme()
        self.assertTrue(self.control.store.audit_chain_check()["ok"])
        with self.control.store._lock:
            first = self.control.store._connection.execute(
                "SELECT sequence FROM audit_logs ORDER BY sequence LIMIT 1"
            ).fetchone()
            self.control.store._connection.execute(
                "UPDATE audit_logs SET details='{\"tampered\":true}' WHERE sequence=?",
                (first["sequence"],),
            )
            self.control.store._connection.commit()
        self.assertFalse(self.control.store.integrity_check()["ok"])

    def test_policy_blocks_ssrf_shell_injection_and_workspace_escape(self):
        task = self._programme()["tasks"][0]
        started = self.control.start_task(task["id"])
        decision = PolicyEngine.validate_tool_action(
            started,
            task["owner_id"],
            "get_project_structure",
            {"path": str(Path(self.temp_dir.name) / "safe")},
        )
        self.assertTrue(decision.allowed)

        lead_programme = self.control.create_program(
            objective="Research public opportunities",
            success_metric="One sourced opportunity",
            workflow_key="lead_to_revenue",
            inputs={"workspace": self.temp_dir.name},
        )
        lead_task = self.control.start_task(lead_programme["tasks"][0]["id"])
        blocked = PolicyEngine.validate_tool_action(
            lead_task,
            lead_task["owner_id"],
            "web_fetch",
            {"url": "http://127.0.0.1:8000/private"},
        )
        self.assertFalse(blocked.allowed)
        self.assertIn("blocked", " ".join(blocked.reasons).lower())

        scoped = GovernedTaskRunner._scope_tool_args(
            "read_file",
            {"path": "README.md"},
            self.temp_dir.name,
        )
        self.assertEqual(
            scoped["path"],
            str((Path(self.temp_dir.name) / "README.md").resolve()),
        )

    def test_explicit_local_mode_is_zero_cost_and_has_no_cloud_fallback(self):
        with patch.dict(
            "os.environ",
            {"AMAURA_MODEL_MODE": "local", "AMAURA_LOCAL_MODEL": "nova:3b"},
            clear=False,
        ):
            route = self.control.models.route(
                "builder",
                remaining_budget_cents=0,
                estimated_tokens=50_000,
            )
        self.assertEqual(route.provider, "local")
        self.assertEqual(route.estimated_cost_cents, 0)
        self.assertIsNone(route.fallback_model_key)


if __name__ == "__main__":
    unittest.main()


def test_cloud_reviewer_uses_distinct_nvidia_model(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    from jarvis.amaura.executor import GovernedReviewRunner

    monkeypatch.setenv("AMAURA_REVIEW_MODE", "cloud")
    monkeypatch.setenv("AMAURA_CLOUD_REVIEW_MODEL", "reviewer/model-b")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("AMAURA_REVIEW_ATTESTATION_KEY", "r" * 64)
    monkeypatch.setenv("AMAURA_STRICT_REVIEW", "1")
    control = AmauraControlPlane(tmp_path / "cloud-review.db")
    try:
        task = control.create_program(
            objective="Verify a cloud-reviewed internal result",
            success_metric="Evidence passes independent review",
            workflow_key="software_delivery",
            inputs={"repository_path": str(tmp_path)},
        )["tasks"][0]
        control.start_task(task["id"], actor="jarvis")
        report = control.evidence.put_text("all checks passed", source="test")
        receipt = control.evidence.put_json(
            {
                "actual_model": "worker/model-a",
                "models_used": ["worker/model-a"],
                "provider": "nvidia",
            },
            source="test:worker-receipt",
        )
        submitted = control.submit_task(
            task["id"],
            actor=task["owner_id"],
            summary="Completed with verified evidence.",
            evidence=[
                {
                    "type": "test_report",
                    "reference": report.reference,
                    "sha256": report.sha256,
                    "success": True,
                },
                {
                    "type": "model_execution_receipt",
                    "reference": receipt.reference,
                    "sha256": receipt.sha256,
                    "success": True,
                },
            ],
        )
        assert submitted["state"] == "awaiting_review"
        seen = {}

        class Client:
            def chat_sync(self, *, model_id, messages, tools=None):
                seen["model_id"] = model_id
                packet = json.loads(messages[-1]["content"].split("\n", 1)[1])
                refs = [item["reference"] for item in packet["evidence"] if item.get("success")]
                decision = {
                    "approve": True,
                    "findings": "Every criterion is supported by immutable evidence.",
                    "criteria": [
                        {
                            "criterion_index": index,
                            "criterion": criterion,
                            "passed": True,
                            "evidence_refs": refs,
                            "notes": "Verified.",
                        }
                        for index, criterion in enumerate(packet["acceptance_criteria"], start=1)
                    ],
                }
                message = SimpleNamespace(content=json.dumps(decision), tool_calls=[])
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        def factory(route, reviewer):
            seen["route"] = route
            return Client()

        result = GovernedReviewRunner(control, client_factory=factory).run(task["id"])
        assert result["approve"] is True
        assert seen["route"]["provider"] == "nvidia"
        assert seen["model_id"] == "reviewer/model-b"
        assert control.store.get_work_item(task["id"])["state"] == "completed"
    finally:
        control.close()


def test_cloud_reviewer_rejects_same_worker_model(monkeypatch, tmp_path):
    from jarvis.amaura.executor import GovernedReviewRunner

    monkeypatch.setenv("AMAURA_REVIEW_MODE", "cloud")
    monkeypatch.setenv("AMAURA_CLOUD_REVIEW_MODEL", "same/model")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("AMAURA_STRICT_REVIEW", "1")
    control = AmauraControlPlane(tmp_path / "same-model-review.db")
    try:
        task = control.create_program(
            objective="Reject correlated review",
            success_metric="Reviewer is independent",
            workflow_key="software_delivery",
            inputs={"repository_path": str(tmp_path)},
        )["tasks"][0]
        control.start_task(task["id"], actor="jarvis")
        report = control.evidence.put_text("checks", source="test")
        receipt = control.evidence.put_json(
            {"actual_model": "same/model", "models_used": ["same/model"]},
            source="test:worker-receipt",
        )
        control.submit_task(
            task["id"],
            actor=task["owner_id"],
            summary="Completed.",
            evidence=[
                {"type": "test_report", "reference": report.reference, "sha256": report.sha256, "success": True},
                {
                    "type": "model_execution_receipt",
                    "reference": receipt.reference,
                    "sha256": receipt.sha256,
                    "success": True,
                },
            ],
        )
        with pytest.raises(GovernanceError, match="must differ"):
            GovernedReviewRunner(control, client_factory=lambda route, reviewer: None).run(task["id"])
    finally:
        control.close()
