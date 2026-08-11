"""Adversarial launch-hardening tests for local Amaura operation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import EvidenceVault, validate_criterion_review
from jarvis.amaura.gitops import (
    WorktreeRecord,
    finalize_task_commit,
    merge_approved_task,
    prepare_task_worktree,
)
from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.runtime import load_amaura_env
from jarvis.amaura.store import CompanyStore
from jarvis.amaura.supervisor import AmauraSupervisor


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / "app.py").write_text("def answer():\n    return 41\n", encoding="utf-8")
    (repository / "test_app.py").write_text(
        "from app import answer\n\ndef test_answer():\n    assert answer() == 42\n",
        encoding="utf-8",
    )
    # Keep the base green while the task later changes the implementation.
    (repository / "test_app.py").write_text(
        "from app import answer\n\ndef test_answer():\n    assert answer() == 41\n",
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial")
    return repository


def _task(record: WorktreeRecord, commit: str, *, validation: str = None) -> dict:
    if validation is None:
        validation = "pytest -q"
    return {
        "id": "task_git_hardening",
        "action_type": "repository_write",
        "metadata": {
            "git_repository_root": record.repository_root,
            "git_worktree_path": record.worktree_path,
            "git_branch": record.branch,
            "git_base_branch": record.base_branch,
            "git_base_commit": record.base_commit,
            "git_commit": commit,
            "post_merge_validation": validation,
        },
    }


def _approved_email(control: AmauraControlPlane) -> tuple[dict, dict]:
    pipeline = control.acquisition
    pipeline.create_campaign(
        campaign_id="launch-reconciliation",
        name="Launch reconciliation",
        target_segment="SaaS founders",
        offer="Product engineering",
        daily_outreach_limit=3,
    )
    lead = pipeline.discover_lead(
        campaign_id="launch-reconciliation",
        company_name="Example",
        domain="example.com",
        source_url="https://example.com/services",
    )
    pipeline.add_evidence(
        lead["id"],
        claim_type="services",
        claim="Lists product services",
        source_url="https://example.com/services",
        source_excerpt="Example publicly lists software and product services for customers.",
        confidence=0.9,
    )
    pipeline.score_lead(
        lead["id"],
        {
            "campaign_fit": 25,
            "visible_need": 20,
            "ability_to_pay": 15,
            "contactability": 15,
            "portfolio_match": 10,
        },
    )
    message = pipeline.stage_message(
        lead["id"],
        recipient="founder@example.com",
        channel="email",
        message_type="first_contact",
        subject="Product engineering",
        body=" ".join(["verified"] * 100),
    )
    message = pipeline.decide_message(
        message["id"],
        actor=control.founder_id,
        approve=True,
        reason="Approved for launch hardening test",
    )
    pipeline.deliver_approved_message(
        message["id"],
        recipient=message["recipient"],
        actor="outreach_agent",
    )
    event = control.store.list_outbox_events(status="pending", limit=1)[0]
    control.store.claim_outbox_events(worker_id="worker-a", limit=1)
    control.store.complete_outbox_event(
        event["id"],
        error="provider timeout after request transmission",
        worker_id="worker-a",
        reconciliation_required=True,
    )
    control.store.mark_message_reconciliation_required(
        message["id"],
        "provider timeout after request transmission",
    )
    return control.store.get_message(message["id"]), control.store.get_outbox_event(event["id"])


class TestRuntimeConfiguration:
    def test_env_loader_does_not_execute_shell_syntax(self, tmp_path, monkeypatch):
        target = tmp_path / ".env.amaura"
        marker = tmp_path / "should-not-exist"
        target.write_text(
            f"AMAURA_TEST_LITERAL=$(touch {marker})\nAMAURA_TEST_QUOTED='safe value'\n",
            encoding="utf-8",
        )
        target.chmod(0o600)
        monkeypatch.delenv("AMAURA_TEST_LITERAL", raising=False)
        monkeypatch.delenv("AMAURA_TEST_QUOTED", raising=False)
        load_amaura_env(target, override=True, require_private_permissions=True)
        assert os.environ["AMAURA_TEST_LITERAL"].startswith("$(touch")
        assert os.environ["AMAURA_TEST_QUOTED"] == "safe value"
        assert not marker.exists()

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
    def test_env_loader_rejects_public_secret_file(self, tmp_path):
        target = tmp_path / ".env.amaura"
        target.write_text("AMAURA_OPERATOR_KEY=secret\n", encoding="utf-8")
        target.chmod(0o644)
        with pytest.raises(PermissionError):
            load_amaura_env(target, override=True, require_private_permissions=True)


class TestCriterionEvidenceContract:
    def test_strict_review_requires_every_criterion_and_real_reference(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AMAURA_STRICT_REVIEW", "1")
        vault = EvidenceVault(tmp_path / "evidence")
        record = vault.put_text("pytest: 12 passed", source="pytest")
        task = {
            "acceptance_criteria": ["Tests pass", "No placeholders"],
            "evidence": [
                {
                    "type": "test_report",
                    "reference": record.reference,
                    "sha256": record.sha256,
                    "success": True,
                }
            ],
        }
        incomplete = validate_criterion_review(
            task,
            {
                "approve": True,
                "criteria": [
                    {
                        "criterion_index": 1,
                        "criterion": "Tests pass",
                        "passed": True,
                        "evidence_refs": [record.reference],
                    }
                ],
            },
            vault,
        )
        assert not incomplete["ok"]
        assert any("missing reviewer coverage" in item for item in incomplete["findings"])

        invalid_reference = validate_criterion_review(
            task,
            {
                "approve": True,
                "criteria": [
                    {
                        "criterion_index": 1,
                        "criterion": "Tests pass",
                        "passed": True,
                        "evidence_refs": [record.reference],
                    },
                    {
                        "criterion_index": 2,
                        "criterion": "No placeholders",
                        "passed": True,
                        "evidence_refs": ["evidence://sha256/" + "0" * 64],
                    },
                ],
            },
            vault,
        )
        assert not invalid_reference["ok"]
        assert any("outside the approved submission" in item for item in invalid_reference["findings"])


class TestOutboxLeases:
    def test_wrong_worker_cannot_complete_claimed_event(self, tmp_path):
        store = CompanyStore(tmp_path / "amaura.db")
        try:
            event = store.enqueue_outbox_event("private", "create_private_draft", {"x": 1}, "idem-1")
            claimed = store.claim_outbox_events(worker_id="worker-a", limit=1)
            assert claimed[0]["id"] == event["id"]
            with pytest.raises(ValueError, match="another worker"):
                store.complete_outbox_event(event["id"], worker_id="worker-b")
        finally:
            store.close()

    def test_expired_email_lease_requires_reconciliation(self, tmp_path):
        store = CompanyStore(tmp_path / "amaura.db")
        try:
            event = store.enqueue_outbox_event(
                "gmail",
                "send_email",
                {"message_id": "", "recipient": "a@example.com"},
                "idem-email",
            )
            store.claim_outbox_events(worker_id="worker-a", limit=1, lease_seconds=30)
            with store._lock:
                store._connection.execute(
                    "UPDATE outbox_events SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
                    (event["id"],),
                )
                store._connection.commit()
            recovered = store.recover_expired_outbox_events()
            assert recovered[0]["status"] == "reconciliation_required"
            assert store.claim_outbox_events(worker_id="worker-b", limit=1) == []
        finally:
            store.close()

    def test_ambiguous_email_dispatch_is_not_replayed(self, tmp_path):
        control = AmauraControlPlane(tmp_path / "amaura.db")
        try:
            event = control.store.enqueue_outbox_event(
                "gmail",
                "send_email",
                {"message_id": "", "recipient": "a@example.com", "subject": "S", "body": "B"},
                "idem-ambiguous",
            )
            supervisor = AmauraSupervisor(control, worker_id="worker-a", automatic_reviews=False)
            with patch("jarvis.amaura.supervisor.dispatch_outbox_event", side_effect=TimeoutError("provider timeout")):
                result = supervisor.tick()
            assert result["outbox_dispatched"][0]["status"] == "reconciliation_required"
            assert control.store.get_outbox_event(event["id"])["status"] == "reconciliation_required"
            with patch("jarvis.amaura.supervisor.dispatch_outbox_event") as dispatch:
                supervisor.tick()
                dispatch.assert_not_called()
        finally:
            control.close()


class TestOutboxFounderReconciliation:
    def test_signed_exact_receipt_completes_quarantined_email(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "AMAURA_PROVIDER_RECEIPT_KEY",
            "launch-hardening-provider-receipt-key-which-is-definitely-over-32-bytes",
        )
        control = AmauraControlPlane(tmp_path / "amaura.db")
        try:
            message, event = _approved_email(control)
            receipt = ProviderReceipt.issue(
                provider="gmail",
                operation="send_email",
                external_id="gmail-message-123",
                idempotency_key=event["idempotency_key"],
                payload={
                    "recipient": message["recipient"],
                    "subject": message["subject"],
                    "body": message["body"],
                },
                status="sent",
            )
            resolved = control.reconcile_outbox_event(
                event["id"],
                resolution="completed",
                reason="Confirmed in Gmail sent folder",
                provider_receipt=receipt,
                actor=control.founder_id,
            )
            assert resolved["status"] == "completed"
            assert control.store.get_message(message["id"])["status"] == "sent"
            assert control.store.get_message(message["id"])["external_message_id"] == "gmail-message-123"
        finally:
            control.close()

    def test_receipt_for_different_payload_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "AMAURA_PROVIDER_RECEIPT_KEY",
            "launch-hardening-provider-receipt-key-which-is-definitely-over-32-bytes",
        )
        control = AmauraControlPlane(tmp_path / "amaura.db")
        try:
            message, event = _approved_email(control)
            receipt = ProviderReceipt.issue(
                provider="gmail",
                operation="send_email",
                external_id="gmail-message-evil",
                idempotency_key=event["idempotency_key"],
                payload={
                    "recipient": "attacker@example.com",
                    "subject": message["subject"],
                    "body": message["body"],
                },
                status="sent",
            )
            with pytest.raises(GovernanceError, match="payload does not match"):
                control.reconcile_outbox_event(
                    event["id"],
                    resolution="completed",
                    reason="Incorrect provider record",
                    provider_receipt=receipt,
                    actor=control.founder_id,
                )
            assert control.store.get_outbox_event(event["id"])["status"] == "reconciliation_required"
            assert control.store.get_message(message["id"])["status"] == "reconciliation_required"
        finally:
            control.close()

    @pytest.mark.parametrize(
        ("resolution", "event_status", "message_status"),
        (("failed", "failed", "failed"), ("requeue", "pending", "sending")),
    )
    def test_founder_can_fail_or_requeue_without_silent_state_drift(
        self,
        tmp_path,
        resolution,
        event_status,
        message_status,
    ):
        control = AmauraControlPlane(tmp_path / "amaura.db")
        try:
            message, event = _approved_email(control)
            resolved = control.reconcile_outbox_event(
                event["id"],
                resolution=resolution,
                reason=f"Founder selected {resolution}",
                actor=control.founder_id,
            )
            assert resolved["status"] == event_status
            assert control.store.get_message(message["id"])["status"] == message_status
        finally:
            control.close()


class TestGitDeliverySafety:
    def test_reviewed_commit_merges_and_validates(self, tmp_path, monkeypatch):
        repository = _repository(tmp_path)
        monkeypatch.setenv("AMAURA_WORKTREE_ROOT", str(tmp_path / "worktrees"))
        record = prepare_task_worktree(repository, "task_git_hardening")
        worktree = Path(record.worktree_path)
        (worktree / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        (worktree / "test_app.py").write_text(
            "from app import answer\n\ndef test_answer():\n    assert answer() == 42\n",
            encoding="utf-8",
        )
        commit = finalize_task_commit(record, task_id="task_git_hardening", title="Fix answer")
        merged = merge_approved_task(_task(record, commit.commit))
        assert _git(repository, "rev-parse", "HEAD") == merged.merged_head
        assert _git(repository, "show", "HEAD:app.py").endswith("return 42")
        assert not Path(record.worktree_path).exists()

    def test_target_advance_invalidates_approval(self, tmp_path, monkeypatch):
        repository = _repository(tmp_path)
        monkeypatch.setenv("AMAURA_WORKTREE_ROOT", str(tmp_path / "worktrees"))
        record = prepare_task_worktree(repository, "task_git_hardening")
        worktree = Path(record.worktree_path)
        (worktree / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        commit = finalize_task_commit(record, task_id="task_git_hardening", title="Fix answer")
        (repository / "README.md").write_text("advanced\n", encoding="utf-8")
        _git(repository, "add", "README.md")
        _git(repository, "commit", "-m", "advance target")
        with pytest.raises(GovernanceError, match="advanced after task creation"):
            merge_approved_task(_task(record, commit.commit))

    def test_failed_validation_rolls_back_merge(self, tmp_path, monkeypatch):
        repository = _repository(tmp_path)
        monkeypatch.setenv("AMAURA_WORKTREE_ROOT", str(tmp_path / "worktrees"))
        record = prepare_task_worktree(repository, "task_git_hardening")
        previous = _git(repository, "rev-parse", "HEAD")
        worktree = Path(record.worktree_path)
        (worktree / "app.py").write_text("def answer():\n    return 99\n", encoding="utf-8")
        commit = finalize_task_commit(record, task_id="task_git_hardening", title="Break answer")
        with pytest.raises(GovernanceError, match="Post-merge validation failed"):
            merge_approved_task(_task(record, commit.commit))
        assert _git(repository, "rev-parse", "HEAD") == previous
        assert _git(repository, "status", "--porcelain") == ""
