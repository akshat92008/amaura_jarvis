"""Production controls for evidence, providers, isolation, and observability."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import (
    EvidenceVault,
    create_review_attestation,
    deterministic_evidence_review,
    verify_review_attestation,
)
from jarvis.amaura.integrations import (
    GmailAdapter,
    PrivatePublicationAdapter,
    ProviderReceipt,
    verify_provider_receipt,
)
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_json, validate_public_url
from jarvis.amaura.readiness import production_readiness
from jarvis.amaura.sandbox import DockerSandbox, run_governed_command

RECEIPT_KEY = "provider-receipt-key-longer-than-thirty-two-bytes"
ATTESTATION_KEY = "review-attestation-key-longer-than-thirty-two-bytes"


class _FakeResponse:
    def __init__(
        self,
        payload: dict,
        *,
        status: int = 200,
        url: str = "https://provider.example.com/v1",
    ):
        self.status = status
        self._payload = json.dumps(payload).encode()
        self._url = url
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount: int) -> bytes:
        return self._payload[:amount]

    def geturl(self) -> str:
        return self._url


class TestAmauraProductionControls(unittest.TestCase):
    def test_evidence_vault_is_content_addressed_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = EvidenceVault(directory)
            first = vault.put_text("complete test output", source="pytest")
            second = vault.put_text("complete test output", source="pytest")
            self.assertEqual(first.sha256, second.sha256)
            self.assertTrue(vault.verify(first.reference)["ok"])
            target = (
                Path(directory)
                / "sha256"
                / first.sha256[:2]
                / first.sha256[2:]
            )
            target.write_text("tampered", encoding="utf-8")
            self.assertFalse(vault.verify(first.reference)["ok"])

    def test_deterministic_review_rejects_failed_and_unvaulted_tool_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            reviewed = deterministic_evidence_review(
                {
                    "id": "task-1",
                    "summary": "Done",
                    "acceptance_criteria": ["Tests pass"],
                    "evidence": [
                        {
                            "type": "tool_result",
                            "reference": "tool:pytest",
                            "success": False,
                        }
                    ],
                },
                EvidenceVault(directory),
            )
        self.assertFalse(reviewed["approve"])
        self.assertGreaterEqual(len(reviewed["findings"]), 2)

    def test_review_attestation_is_signed_and_tamper_evident(self):
        attestation = create_review_attestation(
            task_id="task-1",
            reviewer_id="qa",
            reviewer_model="reviewer-model",
            decision={"approve": True},
            deterministic_review={
                "approve": True,
                "submission_sha256": "a" * 64,
            },
            key=ATTESTATION_KEY,
        )
        self.assertTrue(
            verify_review_attestation(attestation, key=ATTESTATION_KEY)
        )
        attestation["decision"]["approve"] = False
        self.assertFalse(
            verify_review_attestation(attestation, key=ATTESTATION_KEY)
        )

    def test_review_task_accepts_real_object_decision_attestation(self):
        with patch.dict(os.environ, {"AMAURA_REVIEW_ATTESTATION_KEY": ATTESTATION_KEY}):
            control = AmauraControlPlane(Path(tempfile.mkdtemp()) / "amaura.db")
            try:
                created = control.create_program(
                    objective="Verify review contract",
                    success_metric="Object decision attestations approve tasks",
                    workflow_key="software_delivery",
                )
                task = created["tasks"][0]
                control.start_task(task["id"], actor="jarvis")
                control.submit_task(
                    task["id"],
                    actor=task["owner_id"],
                    summary="All criteria are met.",
                    evidence=[{"type": "test_report", "reference": "artifact://review-contract"}],
                )
                decision = {
                    "approve": True,
                    "findings": "Evidence independently verified.",
                    "criteria": [],
                }
                deterministic = deterministic_evidence_review(task, control.evidence)
                attestation = create_review_attestation(
                    task_id=task["id"],
                    reviewer_id=task["reviewer_id"],
                    reviewer_model="reviewer-model",
                    decision=decision,
                    deterministic_review=deterministic,
                )
                updated = control.review_task(
                    task["id"],
                    actor=task["reviewer_id"],
                    approve=True,
                    findings=decision["findings"],
                    attestation=attestation,
                )
                self.assertIn(updated["state"], {"completed", "awaiting_approval"})
            finally:
                control.close()

    def test_provider_receipt_binds_operation_idempotency_and_payload(self):
        payload = {"recipient": "client@example.com", "body": "Approved"}
        receipt = ProviderReceipt.issue(
            provider="gmail",
            operation="send_email",
            external_id="gmail-1",
            idempotency_key="idem-1",
            payload=payload,
            status="sent",
            key=RECEIPT_KEY,
        )
        verified = verify_provider_receipt(
            receipt,
            expected_operation="send_email",
            expected_idempotency_key="idem-1",
            expected_payload=payload,
            key=RECEIPT_KEY,
        )
        self.assertEqual(verified.external_id, "gmail-1")
        with self.assertRaisesRegex(GovernanceError, "payload"):
            verify_provider_receipt(
                receipt,
                expected_operation="send_email",
                expected_payload={"recipient": "other@example.com"},
                key=RECEIPT_KEY,
            )

    def test_gmail_adapter_requires_real_provider_identifier(self):
        calls = []

        def transport(url, **kwargs):
            calls.append((url, kwargs))
            return 200, {"id": "gmail-123", "threadId": "thread-9"}, {}

        adapter = GmailAdapter(
            access_token="oauth-token",
            transport=transport,
            receipt_key=RECEIPT_KEY,
        )
        receipt = adapter.send(
            recipient="client@example.com",
            subject="Approved proposal",
            body="Founder-approved message",
            idempotency_key="message-hash",
        )
        self.assertTrue(receipt.verify(key=RECEIPT_KEY))
        self.assertEqual(receipt.external_id, "gmail-123")
        self.assertEqual(len(calls), 1)

    def test_private_publication_adapter_never_accepts_public_visibility(self):
        adapter = PrivatePublicationAdapter(
            endpoint="https://publisher.example.com/v1/drafts",
            access_token="token",
            transport=lambda *args, **kwargs: (
                201,
                {
                    "id": "draft-1",
                    "visibility": "private",
                    "provider": "test-publisher",
                },
                {},
            ),
            receipt_key=RECEIPT_KEY,
        )
        with patch(
            "jarvis.amaura.integrations.validate_public_url"
        ):
            receipt = adapter.create_private_draft(
                payload={"visibility": "private", "title": "Proof"},
                idempotency_key="draft-key",
            )
            self.assertEqual(receipt.status, "private")
            with self.assertRaisesRegex(GovernanceError, "private"):
                adapter.create_private_draft(
                    payload={"visibility": "public", "title": "Proof"},
                    idempotency_key="public-key",
                )

    def test_dns_resolution_blocks_private_and_metadata_destinations(self):
        private_dns = [
            (2, 1, 6, "", ("169.254.169.254", 80)),
        ]
        with self.assertRaisesRegex(GovernanceError, "blocked"):
            validate_public_url(
                "http://public-looking.example.com/latest/meta-data",
                resolver=lambda *args, **kwargs: private_dns,
            )

    def test_provider_transport_rejects_changed_destination(self):
        opener = SimpleNamespace(
            open=lambda *args, **kwargs: _FakeResponse(
                {"id": "x"},
                url="https://redirected.example.com/private",
            )
        )
        with patch("jarvis.amaura.network.validate_public_url"):
            with self.assertRaisesRegex(GovernanceError, "destination"):
                request_json(
                    "https://provider.example.com/v1",
                    payload={"safe": True},
                    opener=opener,
                )

    def test_docker_sandbox_disables_network_and_drops_privileges(self):
        completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=completed) as runner:
            with tempfile.TemporaryDirectory() as directory:
                result = DockerSandbox(
                    docker_binary="/usr/bin/docker",
                    image="amaura-sandbox:test",
                ).run("pytest -q", workspace=directory)
        arguments = runner.call_args.args[0]
        self.assertIn("none", arguments)
        self.assertIn("ALL", arguments)
        self.assertIn("no-new-privileges", arguments)
        self.assertTrue(result.isolated)
        self.assertTrue(result.network_disabled)

    def test_host_execution_fails_closed_without_break_glass(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "AMAURA_SANDBOX_MODE": "host",
                    "AMAURA_ALLOW_HOST_EXECUTION": "0",
                },
            ):
                with self.assertRaisesRegex(GovernanceError, "disabled"):
                    run_governed_command(
                        "pytest -q",
                        workspace=directory,
                    )

    def test_metrics_traces_and_alerts_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "amaura.db"
            first = AmauraControlPlane(database)
            first.telemetry.increment(
                "amaura_test_total",
                labels={"result": "ok"},
            )
            first.telemetry.alert(
                severity="warning",
                code="test_alert",
                message="Durability test",
            )
            with first.telemetry.trace("test.operation"):
                pass
            first.close()

            second = AmauraControlPlane(database)
            snapshot = second.telemetry.snapshot()
            prometheus = second.telemetry.prometheus()
            second.close()
        self.assertTrue(snapshot["metrics"])
        self.assertTrue(snapshot["alerts"])
        self.assertTrue(snapshot["recent_traces"])
        self.assertIn("amaura_test_total", prometheus)

    def test_readiness_separates_source_from_unavailable_live_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "AMAURA_MODEL_MODE": "local",
                    "AMAURA_LOCAL_MODEL": "worker-model",
                    "AMAURA_LOCAL_REVIEW_MODEL": "reviewer-model",
                    "AMAURA_SANDBOX_MODE": "docker",
                },
            ):
                control = AmauraControlPlane(Path(directory) / "amaura.db")
                report = production_readiness(control, live=False)
                control.close()
        self.assertTrue(report["source_certified"])
        self.assertEqual(report["source_blockers"], [])
        self.assertEqual(report["live_checks"], {})

    def test_static_release_gate_uses_source_certified_not_ready(self):
        from scripts.release_gate import _run

        with patch.dict(
            os.environ,
            {
                "AMAURA_MODEL_MODE": "local",
                "AMAURA_LOCAL_MODEL": "worker-model",
                "AMAURA_LOCAL_REVIEW_MODEL": "reviewer-model",
                "AMAURA_SANDBOX_MODE": "docker",
            },
        ):
            report = _run(static_only=True)
        self.assertIn("source_certified", report)
        self.assertIn("production_ready", report)
        self.assertFalse(report["ready"])
        self.assertFalse(report["production_ready"])

    def test_review_models_must_be_distinct_for_production(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "AMAURA_MODEL_MODE": "local",
                    "AMAURA_LOCAL_MODEL": "same-model",
                    "AMAURA_LOCAL_REVIEW_MODEL": "same-model",
                },
            ):
                control = AmauraControlPlane(Path(directory) / "amaura.db")
                report = production_readiness(control, live=False)
                control.close()
        self.assertFalse(report["checks"]["distinct_reviewer_model"])


if __name__ == "__main__":
    unittest.main()
