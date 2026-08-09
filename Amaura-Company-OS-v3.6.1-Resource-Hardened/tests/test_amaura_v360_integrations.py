from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.amaura.billing import InvoiceService
from jarvis.amaura.channels import AssistedOutreachAdapter, TelegramNotificationAdapter
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.inbox import (
    GmailInboxAdapter,
    InboundMessage,
    InboxService,
    ReplyClassifier,
    parse_meta_webhook,
    verify_meta_signature,
)
from jarvis.amaura.integration_control import IntegrationActionController
from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.nexus_bridge import NexusDeliveryAdapter
from jarvis.amaura.oauth import OAuthTokenProvider
from jarvis.amaura.public_sources import (
    AcquisitionDiscoveryRunner,
    DiscoveredBusiness,
    FreeLeadDiscoveryService,
    SearchHit,
    WebsiteProfile,
)
from jarvis.amaura.supervisor import AmauraSupervisor
from jarvis.amaura.workspace_integrations import GoogleCalendarAdapter, GoogleDriveAdapter, GitHubAdapter

RECEIPT_KEY = "r" * 64


def _qualified_lead(control: AmauraControlPlane, *, contact: str = "alice@example.com") -> dict:
    pipeline = control.acquisition
    pipeline.create_campaign(
        campaign_id="campaign1",
        name="Campaign",
        target_segment="Real estate",
        offer="Lead automation",
        minimum_score=70,
        daily_lead_limit=25,
        daily_outreach_limit=10,
        daily_followup_limit=10,
        maximum_followups=2,
        config={},
    )
    lead = pipeline.discover_lead(
        campaign_id="campaign1",
        company_name="Example Realty",
        domain="example.com",
        source_url="https://example.com",
    )
    control.store.update_lead(lead["id"], public_contact=contact)
    pipeline.add_evidence(
        lead["id"],
        claim_type="public_fact",
        claim="Public website reviewed",
        source_url="https://example.com/contact",
        source_excerpt="Example Realty provides public contact information for prospective customers.",
        confidence=0.9,
    )
    return pipeline.score_lead(
        lead["id"],
        {
            "campaign_fit": 20,
            "visible_need": 20,
            "ability_to_pay": 15,
            "contactability": 15,
            "portfolio_match": 10,
        },
    )


def test_assisted_outreach_is_founder_confirmed_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)
    monkeypatch.setenv("AMAURA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        lead = _qualified_lead(control, contact="https://www.linkedin.com/in/example")
        message = control.acquisition.stage_message(
            lead["id"],
            recipient="https://www.linkedin.com/in/example",
            channel="linkedin",
            message_type="first_contact",
            subject="Lead workflow",
            body=" ".join(["verified"] * 100),
        )
        control.acquisition.decide_message(
            message["id"], actor="founder", approve=True, reason="Exact message approved"
        )
        result = control.acquisition.deliver_approved_message(
            message["id"], recipient=message["recipient"], actor="outreach_agent"
        )
        assert result["requires_founder_send"] is True
        AmauraSupervisor(control, automatic_reviews=False).tick()
        prepared = control.store.get_message(message["id"])
        assert prepared["status"] == "prepared"
        packet = Path(prepared["thread_id"])
        assert packet.is_file()
        data = json.loads(packet.read_text())
        assert data["requires_founder_send"] is True
        assert data["payload"]["body"] == message["body"]
        sent = control.acquisition.record_assisted_send(
            message["id"], actor="founder", external_message_id="founder-reference-1"
        )
        assert sent["status"] == "sent"
        assert control.store.get_lead(lead["id"])["stage"] == "sent"
    finally:
        control.close()


def test_assisted_handoff_is_idempotent_and_never_auto_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)
    adapter = AssistedOutreachAdapter(handoff_dir=tmp_path)
    first = adapter.prepare(
        channel="whatsapp",
        recipient="+919999999999",
        subject="",
        body="Approved text",
        idempotency_key="same-key",
        open_browser=False,
    )
    second = adapter.prepare(
        channel="whatsapp",
        recipient="+919999999999",
        subject="",
        body="Approved text",
        idempotency_key="same-key",
        open_browser=False,
    )
    assert first.external_id == second.external_id
    assert first.status == "prepared"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_inbox_ingestion_classifies_and_stages_founder_review(tmp_path):
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        lead = _qualified_lead(control)
        control.store.update_lead(lead["id"], stage="sent")
        service = InboxService(control.store, "founder")
        inbound, inserted = service.ingest(
            InboundMessage(
                provider="gmail",
                external_id="gmail-1",
                thread_id="thread-1",
                sender="alice@example.com",
                recipient="akshat@example.com",
                subject="Re: automation",
                body="I am interested. Please send more details and schedule a call.",
                received_at=datetime.now(UTC).isoformat(),
                raw_metadata={},
            )
        )
        assert inserted is True
        duplicate, inserted_again = service.ingest(
            InboundMessage(
                provider="gmail", external_id="gmail-1", thread_id="thread-1",
                sender="alice@example.com", recipient="akshat@example.com",
                subject="Re: automation", body="I am interested. Please send more details and schedule a call.",
                received_at=datetime.now(UTC).isoformat(), raw_metadata={},
            )
        )
        assert inserted_again is False
        assert duplicate["id"] == inbound["id"]
        processed = service.process(inbound["id"])
        assert processed["classification"]["label"] == "interested"
        reply_id = processed["classification"]["reply_message_id"]
        assert control.store.get_message(reply_id)["status"] == "awaiting_approval"
        assert control.store.get_lead(lead["id"])["stage"] == "replied"
    finally:
        control.close()


def test_opt_out_is_enforced_immediately(tmp_path):
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        lead = _qualified_lead(control)
        control.store.update_lead(lead["id"], stage="sent")
        service = InboxService(control.store, "founder")
        inbound, _ = service.ingest(
            InboundMessage(
                provider="gmail", external_id="gmail-stop", thread_id="thread-stop",
                sender="alice@example.com", recipient="akshat@example.com", subject="Stop",
                body="Please unsubscribe and do not contact me again.",
                received_at=datetime.now(UTC).isoformat(), raw_metadata={},
            )
        )
        processed = service.process(inbound["id"])
        assert processed["status"] == "opted_out"
        updated = control.store.get_lead(lead["id"])
        assert updated["do_not_contact"] is True
        assert updated["stage"] == "opted_out"
    finally:
        control.close()


def test_gmail_parser_and_meta_signature(monkeypatch):
    message_body = "Hello from Gmail"
    encoded = __import__("base64").urlsafe_b64encode(message_body.encode()).decode().rstrip("=")

    def transport(url, **kwargs):
        if "?q=" in url:
            return 200, {"messages": [{"id": "m1"}]}, {}
        return 200, {
            "id": "m1", "threadId": "t1", "internalDate": "1700000000000",
            "payload": {"mimeType": "text/plain", "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "Akshat <akshat@example.com>"},
                {"name": "Subject", "value": "Reply"},
            ], "body": {"data": encoded}},
        }, {}

    tokens = OAuthTokenProvider("TEST_GMAIL", access_token="token")
    rows = GmailInboxAdapter(token_provider=tokens, transport=transport).list_messages()
    assert rows[0].body == message_body
    assert rows[0].sender == "alice@example.com"

    meta_app_key = "fixture-value-1234567890"
    raw = b'{"object":"whatsapp_business_account","entry":[]}'
    signature = "sha256=" + hmac.new(meta_app_key.encode(), raw, hashlib.sha256).hexdigest()
    verify_meta_signature(raw, signature, meta_app_key)
    with pytest.raises(GovernanceError):
        verify_meta_signature(raw, "sha256=bad", meta_app_key)


def test_meta_webhook_parses_whatsapp_and_messenger():
    whatsapp = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "metadata": {"display_phone_number": "+911234567890"},
            "messages": [{"id": "wamid.1", "from": "919999999999", "timestamp": "1700000000", "type": "text", "text": {"body": "Interested"}}],
        }}]}],
    }
    assert parse_meta_webhook(whatsapp)[0].provider == "whatsapp"
    messenger = {
        "object": "page",
        "entry": [{"messaging": [{"sender": {"id": "a"}, "recipient": {"id": "b"},
                                    "timestamp": 1700000000000, "message": {"mid": "mid.1", "text": "Hello"}}]}],
    }
    assert parse_meta_webhook(messenger)[0].provider == "facebook"


def test_integration_action_requires_founder_and_enqueues_once(tmp_path):
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        actions = IntegrationActionController(control.store, "founder")
        action = actions.stage(
            provider="github", operation="create_github_issue",
            payload={"owner": "amaura", "repo": "nexus", "title": "Bug", "body": "Details"},
        )
        with pytest.raises(GovernanceError):
            actions.decide(action["id"], approve=True, actor="not-founder", reason="No")
        approved = actions.decide(action["id"], approve=True, actor="founder", reason="Approved")
        assert approved["status"] == "enqueued"
        events = control.store.list_outbox_events(limit=20)
        assert len([e for e in events if e["id"] == approved["outbox_event_id"]]) == 1
    finally:
        control.close()


def test_external_kill_switch_blocks_approval_and_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)
    monkeypatch.setenv("AMAURA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        actions = IntegrationActionController(control.store, "founder")
        blocked = actions.stage(
            provider="assisted-browser",
            operation="prepare_assisted_message",
            payload={"channel": "linkedin", "recipient": "https://linkedin.com/in/example", "subject": "", "body": "Approved text"},
        )
        control.store.set_control("external_actions_kill_switch", "on", "founder")
        with pytest.raises(GovernanceError):
            actions.decide(blocked["id"], approve=True, actor="founder", reason="Should remain blocked")
        assert control.store.get_integration_action(blocked["id"])["status"] == "awaiting_approval"
        assert control.store.list_outbox_events(limit=20) == []

        control.store.set_control("external_actions_kill_switch", "off", "founder")
        approved = actions.decide(blocked["id"], approve=True, actor="founder", reason="Reviewed")
        control.store.set_control("external_actions_kill_switch", "on", "founder")
        result = AmauraSupervisor(control, automatic_reviews=False).tick()
        assert result["outbox_dispatched"] == []
        assert control.store.get_outbox_event(approved["outbox_event_id"])["status"] == "pending"

        control.store.set_control("external_actions_kill_switch", "off", "founder")
        result = AmauraSupervisor(control, automatic_reviews=False).tick()
        assert result["outbox_dispatched"][0]["status"] == "completed"
    finally:
        control.close()


def test_provider_circuit_breaker(tmp_path):
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3")
    try:
        for _ in range(3):
            control.store.record_provider_failure("provider-x", "timeout", threshold=3, cooldown_seconds=300)
        allowed, state = control.store.provider_can_attempt("provider-x")
        assert allowed is False
        assert state["state"] == "open"
        control.store.record_provider_success("provider-x")
        assert control.store.provider_can_attempt("provider-x")[0] is True
    finally:
        control.close()


def test_workspace_adapters_issue_signed_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)
    token = OAuthTokenProvider("TEST_GOOGLE", access_token="token")

    def calendar_transport(url, **kwargs):
        return 201, {"id": "event-1", "htmlLink": "https://calendar.google.com/event"}, {}

    calendar = GoogleCalendarAdapter(token_provider=token, transport=calendar_transport)
    receipt = calendar.create_event(
        summary="Review", start={"dateTime": "2026-08-07T10:00:00+05:30"},
        end={"dateTime": "2026-08-07T10:30:00+05:30"}, idempotency_key="calendar-1",
    )
    assert receipt.verify()

    source = tmp_path / "report.txt"
    source.write_text("report")

    def drive_transport(url, **kwargs):
        return 200, b'{"id":"file-1","webViewLink":"https://drive.google.com/file"}', {}

    drive = GoogleDriveAdapter(token_provider=token, transport=drive_transport)
    assert drive.upload_file(path=str(source), idempotency_key="drive-1").verify()

    def github_transport(url, **kwargs):
        return 201, {"id": 123, "html_url": "https://github.com/amaura/nexus/issues/1"}, {}

    github = GitHubAdapter(token="token", transport=github_transport)
    assert github.create_issue(owner="amaura", repo="nexus", title="Bug", body="Details", idempotency_key="gh-1").verify()


def test_telegram_notification_requires_exact_founder_chat(monkeypatch):
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)

    def transport(url, **kwargs):
        return 200, {"ok": True, "result": {"message_id": 7, "chat": {"id": "42"}}}, {}

    adapter = TelegramNotificationAdapter(token="token", chat_id="42", transport=transport)
    assert adapter.send(text="Approval required", idempotency_key="tg-1").verify()


def test_invoice_generation_is_local_and_payment_is_not_self_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_UPI_ID", "amaura@upi")
    control = AmauraControlPlane(tmp_path / "amaura.sqlite3", founder_id="founder")
    try:
        invoice = InvoiceService(control.store).create(
            client_name="Example Client",
            client_email="client@example.com",
            line_items=[{"description": "Automation setup", "quantity": 1, "unit_amount_minor": 250000}],
            tax_minor=0,
        )
        assert invoice["status"] == "draft"
        assert invoice["payment_uri"].startswith("upi://pay?")
        assert Path(invoice["document_path"]).is_file()
        with pytest.raises(GovernanceError):
            InvoiceService(control.store).mark_status(invoice["id"], status="paid", actor="jarvis")
    finally:
        control.close()


def test_public_discovery_runner_persists_evidence_and_scores(tmp_path):
    class FakeService:
        def discover(self, query, *, max_results=10):
            return [DiscoveredBusiness(
                company_name="Acme Realty", domain="acme.example", website="https://acme.example",
                source_url="https://acme.example", source_title="Acme", source_snippet="Public real estate company",
                social_urls={"linkedin": "https://linkedin.com/company/acme"},
                emails=("hello@acme.example",), phones=(),
                observations=({"claim_type": "conversion_gap", "claim": "No contact form found",
                               "source_url": "https://acme.example", "source_excerpt": "Public website has no contact form.",
                               "confidence": 0.8},),
                profile={"has_contact_form": False},
            )]

    control = AmauraControlPlane(tmp_path / "amaura.sqlite3")
    try:
        control.acquisition.create_campaign(
            campaign_id="campaign1", name="Campaign", target_segment="Real estate", offer="Automation",
            minimum_score=70, daily_lead_limit=10, daily_outreach_limit=3,
            daily_followup_limit=5, maximum_followups=2, config={},
        )
        results = AcquisitionDiscoveryRunner(control.acquisition, service=FakeService()).run(
            campaign_id="campaign1", query="real estate"
        )
        assert results[0]["lead"]["stage"] == "qualified"
        assert results[0]["evidence_accepted"] == 1
        assert results[0]["lead"]["public_contact"] == "hello@acme.example"
    finally:
        control.close()


def test_nexus_bridge_uses_argv_timeout_and_result_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", RECEIPT_KEY)
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    script = tmp_path / "fake_nexus.py"
    script.write_text(
        "import argparse,json\n"
        "p=argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--request-file'); p.add_argument('--result-file'); a=p.parse_args()\n"
        "request=json.load(open(a.request_file)); json.dump({'run_id':'run-1','objective':request['objective']},open(a.result_file,'w'))\n"
    )
    adapter = NexusDeliveryAdapter(command=f"{sys.executable} {script}")
    receipt = adapter.run(
        repository_path=str(repository), objective="Run verified task",
        acceptance_criteria=["Tests pass"], idempotency_key="nexus-1", timeout_seconds=60,
    )
    assert receipt.external_id == "run-1"
    assert receipt.verify()


def test_reply_classifier_defaults_to_unclear():
    assert ReplyClassifier().classify("Thanks for the note.")["label"] == "unclear"
