from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jarvis.amaura.billing import InvoiceService
from jarvis.amaura.channels import AssistedOutreachAdapter
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.inbox import GmailInboxAdapter, InboxService, ReplyClassifier
from jarvis.amaura.integration_control import IntegrationActionController
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.oauth import OAuthTokenProvider
from jarvis.amaura.public_sources import RobotsPolicy

RECEIPT_KEY = "r" * 64


def test_reply_classifier_prioritises_rejection_and_plain_stop() -> None:
    classifier = ReplyClassifier()
    assert classifier.classify("not interested")["label"] == "not_interested"
    assert classifier.classify("We are not interested, thanks")["label"] == "not_interested"
    assert classifier.classify("STOP")["label"] == "opt_out"
    assert classifier.classify("Stop emailing me")["label"] == "opt_out"
    assert classifier.classify("No more emails please")["label"] == "opt_out"
    assert classifier.classify("I am interested; send details")["label"] == "interested"


def test_assisted_handoff_does_not_leak_file_descriptors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not Path("/proc/self/fd").is_dir():
        pytest.skip("File descriptor accounting requires /proc")
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)
    adapter = AssistedOutreachAdapter(handoff_dir=tmp_path)
    before = len(list(Path("/proc/self/fd").iterdir()))
    for index in range(50):
        adapter.prepare(
            channel="email",
            recipient="lead@example.com",
            subject="Hello",
            body=f"Approved message {index}",
            idempotency_key=f"handoff-{index}",
            open_browser=False,
        )
    after = len(list(Path("/proc/self/fd").iterdir()))
    assert after - before <= 2


def test_integration_approval_is_atomic_and_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        controller = IntegrationActionController(control.store, "founder")
        action = controller.stage(
            provider="github",
            operation="create_github_issue",
            payload={"owner": "amaura", "repo": "nexus", "title": "Bug", "body": "Details"},
        )
        original = control.store.enqueue_outbox_event

        def fail_enqueue(*args, **kwargs):
            raise RuntimeError("simulated enqueue failure")

        monkeypatch.setattr(control.store, "enqueue_outbox_event", fail_enqueue)
        with pytest.raises(RuntimeError, match="simulated enqueue failure"):
            controller.decide(action["id"], approve=True, actor="founder", reason="Approved")
        rolled_back = control.store.get_integration_action(action["id"])
        assert rolled_back["status"] == "awaiting_approval"
        assert rolled_back["outbox_event_id"] is None
        assert control.store.list_outbox_events(limit=10) == []

        monkeypatch.setattr(control.store, "enqueue_outbox_event", original)
        approved = controller.decide(action["id"], approve=True, actor="founder", reason="Approved")
        assert approved["status"] == "enqueued"
        assert control.store.get_outbox_event(approved["outbox_event_id"])["status"] == "pending"
    finally:
        control.close()


def test_legacy_approved_without_outbox_is_recovered(tmp_path: Path) -> None:
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        controller = IntegrationActionController(control.store, "founder")
        action = controller.stage(
            provider="github",
            operation="create_github_issue",
            payload={"owner": "amaura", "repo": "nexus", "title": "Repair", "body": "Legacy state"},
        )
        control.store.approve_integration_action(
            action["id"], actor="founder", approved=True, reason="legacy partial commit"
        )
        repaired = controller.decide(action["id"], approve=True, actor="founder", reason="recover")
        assert repaired["status"] == "enqueued"
        assert repaired["outbox_event_id"]
    finally:
        control.close()


def test_integration_risk_cannot_be_downgraded(tmp_path: Path) -> None:
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        controller = IntegrationActionController(control.store, "founder")
        with pytest.raises(GovernanceError, match="cannot be lower than high"):
            controller.stage(
                provider="github",
                operation="dispatch_github_workflow",
                payload={"owner": "amaura", "repo": "nexus", "workflow": "ci.yml"},
                risk="low",
            )
        elevated = controller.stage(
            provider="github",
            operation="create_github_issue",
            payload={"owner": "amaura", "repo": "nexus", "title": "Security", "body": "Review"},
            risk="high",
        )
        assert elevated["risk"] == "high"
    finally:
        control.close()


def test_robots_fetch_failure_fails_closed() -> None:
    def unavailable(*args, **kwargs):
        raise OSError("offline")

    policy = RobotsPolicy(unavailable)
    assert policy.allowed("https://example.com/contact") is False


def test_invoice_idempotency_and_state_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_UPI_ID", "amaura@upi")
    monkeypatch.setenv("AMAURA_FOUNDER_ID", "founder")
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        service = InvoiceService(control.store)
        kwargs = {
            "client_name": "Example Client",
            "client_email": "client@example.com",
            "line_items": [{"description": "Automation", "quantity": 1, "unit_amount_minor": 100000}],
            "due_date": "2026-08-31",
            "idempotency_key": "invoice-request-1",
        }
        first = service.create(**kwargs)
        second = service.create(**kwargs)
        assert first["id"] == second["id"]
        assert len(control.store.list_invoices()) == 1

        with pytest.raises(GovernanceError, match="draft -> paid"):
            service.mark_status(first["id"], status="paid", actor="founder", reference="upi-1")
        with pytest.raises(GovernanceError, match="Founder confirmation"):
            service.mark_status(first["id"], status="approved", actor="jarvis")

        assert service.mark_status(first["id"], status="approved", actor="founder")["status"] == "approved"
        assert (
            service.mark_status(first["id"], status="sent", actor="founder", reference="gmail-message-1")["status"]
            == "sent"
        )
        with pytest.raises(GovernanceError, match="requires a reference"):
            service.mark_status(first["id"], status="paid", actor="founder")
        paid = service.mark_status(first["id"], status="paid", actor="founder", reference="upi-transaction-1")
        assert paid["payment_reference"] == "upi-transaction-1"
        with pytest.raises(GovernanceError, match="paid -> void"):
            service.mark_status(first["id"], status="void", actor="founder", reference="reverse")

        events = control.store.list_invoice_status_events(first["id"])
        assert [(event["from_status"], event["to_status"]) for event in events] == [
            ("draft", "approved"),
            ("approved", "sent"),
            ("sent", "paid"),
        ]

        with pytest.raises(GovernanceError, match="YYYY-MM-DD"):
            service.create(
                client_name="Bad Date",
                line_items=[{"description": "Work", "quantity": 1, "unit_amount_minor": 1}],
                due_date="31/08/2026",
                idempotency_key="bad-date",
            )
    finally:
        control.close()


def test_gmail_sync_paginates_and_acknowledges_durable_messages(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def encoded(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    def transport(url: str, **kwargs):
        method = kwargs.get("method", "GET")
        calls.append((method, url))
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/messages"):
            if query.get("pageToken") == ["page-2"]:
                return 200, {"messages": [{"id": "m3"}]}, {}
            return 200, {"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "page-2"}, {}
        if parsed.path.endswith("/modify"):
            return 200, {"id": parsed.path.split("/")[-2], "labelIds": ["INBOX"]}, {}
        message_id = parsed.path.rsplit("/", 1)[-1]
        number = int(message_id.removeprefix("m"))
        return (
            200,
            {
                "id": message_id,
                "threadId": f"thread-{number}",
                "historyId": str(100 + number),
                "internalDate": str(int(datetime(2026, 8, number, tzinfo=UTC).timestamp() * 1000)),
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": f"Lead {number} <lead{number}@example.com>"},
                        {"name": "To", "value": "Akshat <akshat@example.com>"},
                        {"name": "Subject", "value": f"Reply {number}"},
                    ],
                    "body": {"data": encoded(f"Reply body {number}")},
                },
            },
            {},
        )

    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        adapter = GmailInboxAdapter(
            token_provider=OAuthTokenProvider("TEST_GMAIL", access_token="token"),
            transport=transport,
        )
        inserted = InboxService(control.store, "founder").sync_gmail(
            adapter=adapter,
            max_results=3,
            mark_read=True,
        )
        assert len(inserted) == 3
        assert len([call for call in calls if call[1].endswith("/modify")]) == 3
        list_calls = [call for call in calls if urlsplit(call[1]).path.endswith("/messages")]
        assert len(list_calls) == 2
        cursor = control.store.get_integration_cursor("gmail")
        assert cursor is not None
        assert cursor["cursor"] == "103"
        assert cursor["metadata"]["acknowledged"] == 3
    finally:
        control.close()
