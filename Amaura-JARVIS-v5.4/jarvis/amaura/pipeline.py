"""Ethical, evidence-backed and approval-gated client-acquisition pipeline."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from jarvis.amaura.integrations import (
    GmailAdapter,
    N8nEmailAdapter,
    ProviderReceipt,
    verify_provider_receipt,
)
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.security import redact_sensitive_text, scan_untrusted_text
from jarvis.amaura.store import CompanyStore


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class LeadStage(StrEnum):
    DISCOVERED = "discovered"
    RESEARCHING = "researching"
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    OUTREACH_DRAFTED = "outreach_drafted"
    AWAITING_APPROVAL = "awaiting_approval"
    SENT = "sent"
    FOLLOWUP_DUE = "followup_due"
    REPLIED = "replied"
    DISCOVERY = "discovery"
    PROPOSAL_DRAFTED = "proposal_drafted"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    WON = "won"
    DELIVERY = "delivery"
    COMPLETED = "completed"
    TESTIMONIAL_REQUESTED = "testimonial_requested"
    REJECTED = "rejected"
    LOST = "lost"
    OPTED_OUT = "opted_out"
    INVALID_CONTACT = "invalid_contact"
    DUPLICATE = "duplicate"


TERMINAL_STAGES = {LeadStage.REJECTED, LeadStage.LOST, LeadStage.OPTED_OUT, LeadStage.INVALID_CONTACT, LeadStage.DUPLICATE}
ALLOWED_TRANSITIONS: dict[LeadStage, set[LeadStage]] = {
    LeadStage.DISCOVERED: {LeadStage.RESEARCHING, LeadStage.REJECTED, LeadStage.DUPLICATE},
    LeadStage.RESEARCHING: {LeadStage.RESEARCHED, LeadStage.REJECTED, LeadStage.INVALID_CONTACT},
    LeadStage.RESEARCHED: {LeadStage.QUALIFIED, LeadStage.REJECTED, LeadStage.INVALID_CONTACT},
    LeadStage.QUALIFIED: {LeadStage.OUTREACH_DRAFTED, LeadStage.REJECTED},
    LeadStage.OUTREACH_DRAFTED: {LeadStage.AWAITING_APPROVAL, LeadStage.REJECTED},
    LeadStage.AWAITING_APPROVAL: {LeadStage.SENT, LeadStage.OUTREACH_DRAFTED, LeadStage.REJECTED},
    LeadStage.SENT: {LeadStage.FOLLOWUP_DUE, LeadStage.REPLIED, LeadStage.OPTED_OUT, LeadStage.LOST},
    LeadStage.FOLLOWUP_DUE: {LeadStage.AWAITING_APPROVAL, LeadStage.REPLIED, LeadStage.OPTED_OUT, LeadStage.LOST},
    LeadStage.REPLIED: {LeadStage.DISCOVERY, LeadStage.LOST, LeadStage.OPTED_OUT},
    LeadStage.DISCOVERY: {LeadStage.PROPOSAL_DRAFTED, LeadStage.NEGOTIATION, LeadStage.LOST},
    LeadStage.PROPOSAL_DRAFTED: {LeadStage.PROPOSAL_SENT, LeadStage.DISCOVERY, LeadStage.LOST},
    LeadStage.PROPOSAL_SENT: {LeadStage.NEGOTIATION, LeadStage.WON, LeadStage.LOST},
    LeadStage.NEGOTIATION: {LeadStage.WON, LeadStage.LOST, LeadStage.PROPOSAL_DRAFTED},
    LeadStage.WON: {LeadStage.DELIVERY},
    LeadStage.DELIVERY: {LeadStage.COMPLETED},
    LeadStage.COMPLETED: {LeadStage.TESTIMONIAL_REQUESTED},
    LeadStage.TESTIMONIAL_REQUESTED: set(),
}

SCORE_LIMITS = {
    "campaign_fit": 25,
    "visible_need": 25,
    "ability_to_pay": 20,
    "contactability": 15,
    "portfolio_match": 15,
}

ALLOWED_RECEIPTS: dict[str, set[str]] = {
    "gmail": {"send_email"},
    "n8n": {"send_email"},
    "imessage": {"send_imessage"},
    "founder-confirmed": {"confirm_assisted_send"},
}


def normalize_domain(value: str) -> str:
    candidate = value.strip().lower()
    if not candidate:
        raise GovernanceError("A company domain is required")
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    domain = (parsed.hostname or "").rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain or len(domain) > 253 or "." not in domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
        raise GovernanceError(f"Invalid public company domain: {value}")
    return domain


def _public_http_url(url: str) -> tuple[bool, str]:
    if not url or not url.startswith(("http://", "https://")):
        return False, "URL must start with http:// or https://"
    try:
        from jarvis.amaura.network import validate_public_url
        validate_public_url(url, resolve=False)
    except GovernanceError as exc:
        return False, str(exc)
    else:
        return True, ""


class AcquisitionPipeline:
    """Application service enforcing state, evidence, limits, approvals, and idempotency."""

    def __init__(self, store: CompanyStore, founder_id: str = "founder"):
        self.store = store
        self.founder_id = founder_id

    def create_campaign(self, *, campaign_id: str, name: str, target_segment: str, offer: str,
                        minimum_score: int = 70, daily_lead_limit: int = 10,
                        daily_outreach_limit: int = 3, daily_followup_limit: int = 5,
                        maximum_followups: int = 2, config: dict | None = None) -> dict:
        if not all(value.strip() for value in (campaign_id, name, target_segment, offer)):
            raise GovernanceError("Campaign id, name, target segment, and offer are required")
        if not 70 <= minimum_score <= 100:
            raise GovernanceError("Campaign minimum score must be between 70 and 100")
        if not 1 <= daily_lead_limit <= 100 or not 0 <= daily_outreach_limit <= 50:
            raise GovernanceError("Campaign daily limits are outside the governed envelope")
        if not 0 <= daily_followup_limit <= 100 or not 0 <= maximum_followups <= 2:
            raise GovernanceError("A campaign may use at most two follow-ups")
        campaign = self.store.upsert_campaign({
            "id": campaign_id, "name": name.strip(), "target_segment": target_segment.strip(),
            "offer": offer.strip(), "minimum_score": minimum_score,
            "daily_lead_limit": daily_lead_limit, "daily_outreach_limit": daily_outreach_limit,
            "daily_followup_limit": daily_followup_limit, "maximum_followups": maximum_followups,
            "config": config or {},
        })
        self._event(None, campaign_id, "campaign.configured", "campaign_manager", campaign, campaign)
        return campaign

    def discover_lead(self, *, campaign_id: str, company_name: str, domain: str, source_url: str,
                      country: str = "", industry: str = "", metadata: dict | None = None) -> dict:
        self._require_running("discovery")
        campaign = self.store.get_campaign(campaign_id)
        if not campaign["active"]:
            raise GovernanceError("Campaign is paused")
        today = datetime.now(UTC).date().isoformat()
        clean_domain = normalize_domain(domain)
        duplicate = self.store.get_lead_by_domain(clean_domain)
        if duplicate:
            return {**duplicate, "duplicate": True}
        safe_url, url_reason = _public_http_url(source_url)
        if not safe_url:
            raise GovernanceError(f"Lead discovery requires a valid public source URL: {url_reason}")
        try:
            lead = self.store.insert_lead({
                "id": _id("lead"), "campaign_id": campaign_id, "company_name": company_name.strip(),
                "domain": clean_domain, "country": country.strip(), "industry": industry.strip(),
                "metadata": {"discovery_source": source_url, **(metadata or {})},
            }, daily_limit=campaign["daily_lead_limit"], day_prefix=today)
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
        except sqlite3.IntegrityError:
            duplicate = self.store.get_lead_by_domain(clean_domain)
            if duplicate:
                return {**duplicate, "duplicate": True}
            raise
        self._event(lead["id"], campaign_id, "lead.discovered", "lead_scout", {"domain": clean_domain}, lead)
        return lead

    def add_evidence(self, lead_id: str, *, claim_type: str, claim: str, source_url: str,
                     source_excerpt: str, confidence: float, actor: str = "prospect_research") -> dict:
        lead = self.store.get_lead(lead_id)
        safe_url, url_reason = _public_http_url(source_url)
        if not safe_url or not source_excerpt.strip():
            raise GovernanceError(f"Evidence requires a valid public source URL and exact excerpt: {url_reason}")
        if not 0 <= confidence <= 1:
            raise GovernanceError("Evidence confidence must be between 0 and 1")
        scan = scan_untrusted_text(source_excerpt)
        # Priority-1: quarantine injection-flagged evidence — do not store or use it.
        if not scan.safe:
            raise GovernanceError(
                f"Evidence rejected: prompt-injection pattern detected in source excerpt "
                f"(findings: {', '.join(scan.findings)}). Manual review required before "
                "this lead evidence can be accepted."
            )
        safe_excerpt = redact_sensitive_text(source_excerpt.strip())
        digest = hashlib.sha256(f"{claim_type}\0{claim}\0{source_url}\0{safe_excerpt}".encode()).hexdigest()
        try:
            evidence = self.store.add_lead_evidence({
                "id": _id("evidence"), "lead_id": lead_id, "claim_type": claim_type.strip(),
                "claim": claim.strip(), "source_url": source_url, "source_excerpt": safe_excerpt,
                "confidence": confidence, "content_hash": digest,
            })
        except sqlite3.IntegrityError as exc:
            raise GovernanceError("This evidence record already exists") from exc
        self._event(lead_id, lead["campaign_id"], "evidence.recorded", actor,
                    {"content_hash": digest}, {"evidence_id": evidence["id"], "security_scan": scan.to_dict()})
        return {**evidence, "security_scan": scan.to_dict()}

    def score_lead(self, lead_id: str, components: dict[str, int], *, actor: str = "") -> dict:
        if set(components) != set(SCORE_LIMITS):
            raise GovernanceError(f"Score requires exactly: {', '.join(SCORE_LIMITS)}")
        for key, maximum in SCORE_LIMITS.items():
            value = components[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise GovernanceError(f"Score '{key}' must be an integer from 0 to {maximum}")
        lead = self.store.get_lead(lead_id)
        campaign = self.store.get_campaign(lead["campaign_id"])
        total = sum(components.values())
        evidence = self.store.list_lead_evidence(lead_id)
        if total >= campaign["minimum_score"] and not evidence:
            raise GovernanceError("A lead cannot be qualified without verified evidence")
        next_stage = LeadStage.QUALIFIED if total >= campaign["minimum_score"] else LeadStage.REJECTED
        current = LeadStage(lead["stage"])
        if current not in {LeadStage.RESEARCHED, LeadStage.RESEARCHING, LeadStage.DISCOVERED}:
            raise GovernanceError(f"Lead cannot be scored from stage '{current.value}'")
        updated = self.store.update_lead(lead_id, total_score=total, score_components=components,
                                         stage=next_stage.value,
                                         next_action="prepare evidence-backed outreach" if next_stage is LeadStage.QUALIFIED else "")
        self._event(lead_id, lead["campaign_id"], "lead.scored", "lead_qualification", components,
                    {"total": total, "stage": next_stage.value})
        return updated

    def transition(self, lead_id: str, to_stage: str, *, actor: str, reason: str) -> dict:
        lead = self.store.get_lead(lead_id)
        current, target = LeadStage(lead["stage"]), LeadStage(to_stage)
        if current in TERMINAL_STAGES:
            raise GovernanceError(f"Terminal lead '{current.value}' cannot transition")
        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            raise GovernanceError(f"Invalid pipeline transition: {current.value} -> {target.value}")
        if not reason.strip():
            raise GovernanceError("Every pipeline transition requires a reason")
        fields: dict[str, object] = {"stage": target.value}
        if target is LeadStage.OPTED_OUT:
            fields.update(do_not_contact=True, opt_out_reason=reason.strip(), next_action="", next_action_at=None)
        updated = self.store.update_lead(lead_id, **fields)
        self._event(lead_id, lead["campaign_id"], f"lead.{target.value}", actor,
                    {"from": current.value, "reason": reason}, {"to": target.value})
        return updated

    def stage_message(self, lead_id: str, *, recipient: str, channel: str, message_type: str, subject: str,
                      body: str, actor: str = "outreach_writer") -> dict:
        if not recipient.strip():
            raise GovernanceError("A recipient address is required to stage a message (P0-6)")
        if channel == "email" and not re.fullmatch(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", recipient.strip()):
            raise GovernanceError(f"Invalid email recipient address: {recipient}")
        lead = self.store.get_lead(lead_id)
        campaign = self.store.get_campaign(lead["campaign_id"])
        if lead["do_not_contact"] or LeadStage(lead["stage"]) in TERMINAL_STAGES:
            raise GovernanceError("Lead is blocked from contact")
        if message_type == "first_contact" and lead["total_score"] < campaign["minimum_score"]:
            raise GovernanceError("Only leads meeting the campaign score may receive outreach")
        evidence = self.store.list_lead_evidence(lead_id)
        if not evidence:
            raise GovernanceError("Prospect-specific outreach requires source-linked evidence")
        words = len(re.findall(r"\b\w+[\w'-]*\b", body))
        if message_type == "first_contact" and not 70 <= words <= 170:
            raise GovernanceError("First-contact outreach must contain 70-170 words")
        followups = [m for m in self.store.list_messages(lead_id=lead_id) if m["message_type"] == "followup"]
        if message_type == "followup" and len(followups) >= campaign["maximum_followups"]:
            raise GovernanceError("Maximum follow-up count reached")
        payload = {"lead_id": lead_id, "recipient": recipient.strip(), "channel": channel,
                   "message_type": message_type, "subject": subject.strip(), "body": body.strip()}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        existing = self.store.get_idempotency(key)
        if existing:
            return self.store.get_message(existing["resource_id"])
        message = self.store.insert_message({
            "id": _id("message"), **payload, "status": "awaiting_approval", "idempotency_key": key,
            "evidence_snapshot": [{"id": e["id"], "content_hash": e["content_hash"]} for e in evidence],
        })
        self.store.record_idempotency(key, "stage_message", message["id"], hashlib.sha256(body.encode()).hexdigest())
        current = LeadStage(lead["stage"])
        if current is LeadStage.QUALIFIED:
            self.store.update_lead(lead_id, stage=LeadStage.AWAITING_APPROVAL.value)
        self._event(lead_id, lead["campaign_id"], "message.awaiting_approval", actor, payload,
                    {"message_id": message["id"], "idempotency_key": key})
        return message

    def decide_message(self, message_id: str, *, actor: str, approve: bool, reason: str) -> dict:
        if actor != self.founder_id:
            raise GovernanceError("Only the founder may approve outbound messages")
        if not reason.strip():
            raise GovernanceError("Approval decisions require a reason")
        message = self.store.get_message(message_id)
        if message["status"] != "awaiting_approval":
            raise GovernanceError(f"Message is already {message['status']}")
        created = datetime.fromisoformat(message["created_at"])
        if datetime.now(UTC) - created > timedelta(hours=48):
            updated = self.store.update_message(message_id, status="stale")
        elif approve:
            # Compute and lock the exact payload hash at approval time (P0-6).
            approval_payload = {
                "recipient": message["recipient"],
                "subject": message["subject"],
                "body": message["body"],
                "channel": message["channel"],
                "lead_id": message["lead_id"],
                "idempotency_key": message["idempotency_key"],
            }
            payload_hash = hashlib.sha256(
                json.dumps(approval_payload, sort_keys=True).encode()
            ).hexdigest()
            updated = self.store.update_message(
                message_id, status="approved", approved_by=actor,
                approved_at=datetime.now(UTC).isoformat(),
                approved_payload_hash=payload_hash,
            )
        else:
            updated = self.store.update_message(message_id, status="rejected", approved_by=actor,
                                                approved_at=datetime.now(UTC).isoformat())
        lead = self.store.get_lead(message["lead_id"])
        self._event(lead["id"], lead["campaign_id"], f"message.{updated['status']}", actor,
                    {"message_id": message_id, "reason": reason}, {"status": updated["status"]})
        return updated

    def confirm_external_send(
        self,
        message_id: str,
        *,
        actor: str,
        provider_receipt: ProviderReceipt | dict | None = None,
        external_message_id: str = "",
        thread_id: str = "",
    ) -> dict:
        """Record a signed provider receipt after an approved external send."""
        self._require_running("sending")
        message = self.store.get_message(message_id)
        if message["status"] == "sent":
            return message
        if message["status"] not in {
            "approved",
            "sending",
            "queued",
            "dispatching",
            "prepared",
            "reconciliation_required",
        }:
            raise GovernanceError(f"Message status '{message['status']}' cannot be confirmed as sent")
        if message["status"] == "reconciliation_required" and provider_receipt is None:
            raise GovernanceError(
                "A reconciliation-required message can only be completed with a signed provider receipt"
            )
        provider_name = "manual-break-glass"
        if provider_receipt is not None:
            raw_receipt = (
                provider_receipt
                if isinstance(provider_receipt, ProviderReceipt)
                else ProviderReceipt.from_dict(provider_receipt)
            )
            allowed_operations = ALLOWED_RECEIPTS.get(raw_receipt.provider, set())
            if raw_receipt.operation not in allowed_operations:
                raise GovernanceError(
                    "Provider receipt operation is not allowed for this provider"
                )
            if raw_receipt.operation == "send_imessage":
                expected_payload = {"recipient": message["recipient"], "body": message["body"]}
            elif raw_receipt.operation == "confirm_assisted_send":
                expected_payload = {
                    "recipient": message["recipient"], "subject": message["subject"],
                    "body": message["body"], "channel": message["channel"],
                }
            else:
                expected_payload = {
                    "recipient": message["recipient"], "subject": message["subject"], "body": message["body"],
                }
            receipt = verify_provider_receipt(
                raw_receipt,
                expected_operation=raw_receipt.operation,
                expected_idempotency_key=message["idempotency_key"],
                expected_payload=expected_payload,
            )
            if receipt.status != "sent":
                raise GovernanceError(
                    "Only a signed sent receipt can confirm outreach"
                )
            external_message_id = receipt.external_id
            thread_id = receipt.thread_id
            provider_name = receipt.provider
        elif os.environ.get("AMAURA_ALLOW_MANUAL_PROVIDER_CONFIRMATION") == "1":
            if not external_message_id.strip():
                raise GovernanceError(
                    "No silent success: a provider message identifier is required"
                )
        else:
            raise GovernanceError(
                "A signed provider receipt is required; manual success claims "
                "are disabled"
            )
        lead = self.store.get_lead(message["lead_id"])
        if lead["do_not_contact"]:
            raise GovernanceError("Lead opted out after approval; sending is blocked")
        campaign = self.store.get_campaign(lead["campaign_id"])
        today = datetime.now(UTC).date().isoformat()
        is_followup = message["message_type"] == "followup"
        limit = campaign["daily_followup_limit"] if is_followup else campaign["daily_outreach_limit"]
        try:
            updated = self.store.confirm_message_sent_atomic(
                message_id, campaign_id=campaign["id"], is_followup=is_followup,
                daily_limit=limit, since=today, external_message_id=external_message_id.strip(),
                thread_id=thread_id.strip() or None,
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise GovernanceError(str(exc)) from exc
        next_at = datetime.now(UTC) + timedelta(days=4 if message["message_type"] == "first_contact" else 5)
        self.store.update_lead(lead["id"], stage=LeadStage.SENT.value, next_action="review reply or prepare follow-up",
                               next_action_at=next_at.isoformat())
        self._event(lead["id"], lead["campaign_id"], "message.sent", actor,
                    {"message_id": message_id}, {
                        "external_message_id": external_message_id,
                        "provider": provider_name,
                    })
        return updated

    def confirm_assisted_handoff(
        self, message_id: str, *, provider_receipt: ProviderReceipt | dict, actor: str = "jarvis"
    ) -> dict:
        message = self.store.get_message(message_id)
        if message["status"] == "prepared":
            return message
        if message["status"] not in {"sending", "queued", "dispatching"}:
            raise GovernanceError("Assisted handoff is not awaiting preparation")
        expected_payload = {
            "recipient": message["recipient"], "subject": message["subject"],
            "body": message["body"], "channel": message["channel"],
        }
        receipt = verify_provider_receipt(
            provider_receipt, expected_operation="prepare_assisted_message",
            expected_idempotency_key=message["idempotency_key"], expected_payload=expected_payload,
        )
        if receipt.provider != "assisted-browser" or receipt.status != "prepared":
            raise GovernanceError("Assisted handoff receipt is invalid")
        updated = self.store.update_message(
            message_id, status="prepared", external_message_id=receipt.external_id, thread_id=receipt.thread_id,
        )
        lead = self.store.get_lead(message["lead_id"])
        self._event(lead["id"], lead["campaign_id"], "message.prepared", actor,
                    {"message_id": message_id}, {"handoff_id": receipt.external_id, "packet": receipt.thread_id})
        return updated

    def record_assisted_send(
        self, message_id: str, *, actor: str, external_message_id: str, thread_id: str = ""
    ) -> dict:
        if actor != self.founder_id:
            raise GovernanceError("Only the founder may confirm an assisted send")
        message = self.store.get_message(message_id)
        if message["status"] != "prepared":
            raise GovernanceError("Only a prepared handoff can be confirmed as sent")
        if not external_message_id.strip():
            raise GovernanceError("The platform message identifier or founder reference is required")
        receipt = ProviderReceipt.issue(
            provider="founder-confirmed", operation="confirm_assisted_send",
            external_id=external_message_id.strip(), thread_id=thread_id.strip(),
            idempotency_key=message["idempotency_key"],
            payload={"recipient": message["recipient"], "subject": message["subject"],
                     "body": message["body"], "channel": message["channel"]},
            status="sent",
        )
        return self.confirm_external_send(message_id, actor=actor, provider_receipt=receipt)

    def deliver_approved_message(
        self,
        message_id: str,
        *,
        recipient: str,
        actor: str,
        adapter: GmailAdapter | N8nEmailAdapter | None = None,
    ) -> dict:
        """Call Gmail once and atomically persist only its signed success receipt."""

        message = self.store.get_message(message_id)
        if message["status"] == "sent":
            return message
        if message["status"] in {"sending", "reconciliation_required"}:
            raise GovernanceError(
                "Message has an unresolved provider attempt and requires reconciliation before retry"
            )
        if message["status"] != "approved":
            raise GovernanceError("Only an approved message can be delivered")

        # P0-6: verify the delivery recipient matches the approved recipient.
        stored_recipient = message.get("recipient", "").strip()
        if stored_recipient and not hmac.compare_digest(stored_recipient, recipient.strip()):
            raise GovernanceError(
                "Delivery recipient does not match the approved recipient — "
                "the message cannot be re-targeted after approval"
            )

        # P0-6: re-verify the approved payload hash has not been tampered with.
        if message.get("approved_payload_hash"):
            current_payload = {
                "recipient": message["recipient"],
                "subject": message["subject"],
                "body": message["body"],
                "channel": message["channel"],
                "lead_id": message["lead_id"],
                "idempotency_key": message["idempotency_key"],
            }
            current_hash = hashlib.sha256(
                json.dumps(current_payload, sort_keys=True).encode()
            ).hexdigest()
            if not hmac.compare_digest(current_hash, message["approved_payload_hash"]):
                raise GovernanceError(
                    "Approved payload hash mismatch — message content was altered after approval"
                )

        self.store.mark_message_sending(message_id)
        try:
            if message["channel"] == "email":
                payload = {
                    "message_id": message_id,
                    "recipient": message["recipient"],
                    "subject": message["subject"],
                    "body": message["body"],
                    "actor": actor,
                }
                self.store.enqueue_outbox_event(
                    provider="auto",
                    operation="send_email",
                    payload=payload,
                    idempotency_key=message["idempotency_key"],
                )
                return {"status": "enqueued", "message_id": message_id}
            if message["channel"] == "imessage":
                payload = {
                    "message_id": message_id,
                    "recipient": message["recipient"],
                    "body": message["body"],
                    "actor": actor,
                }
                self.store.enqueue_outbox_event(
                    provider="imessage", operation="send_imessage", payload=payload,
                    idempotency_key=message["idempotency_key"],
                )
                return {"status": "enqueued", "message_id": message_id}
            if message["channel"] in {"whatsapp", "linkedin", "instagram", "facebook"}:
                payload = {
                    "message_id": message_id, "recipient": message["recipient"],
                    "subject": message["subject"], "body": message["body"],
                    "channel": message["channel"], "actor": actor,
                }
                self.store.enqueue_outbox_event(
                    provider="assisted-browser", operation="prepare_assisted_message", payload=payload,
                    idempotency_key=message["idempotency_key"],
                )
                return {"status": "enqueued", "message_id": message_id, "requires_founder_send": True}
            raise GovernanceError(f"Unsupported channel: {message['channel']}")
        except Exception as exc:
            self.store.mark_message_reconciliation_required(
                message_id,
                f"{type(exc).__name__}: {exc}",
            )
            raise

    def update_crm(self, lead_id: str, fields: dict, actor: str = "jarvis") -> dict:
        """Queue an exact, auditable CRM synchronization without direct side effects."""
        if actor not in {"jarvis", self.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may synchronize CRM state")
        lead = self.store.get_lead(lead_id)
        if not isinstance(fields, dict) or not fields:
            raise GovernanceError("CRM fields must be a non-empty object")
        encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode()
        if len(encoded) > 100_000:
            raise GovernanceError("CRM update exceeds the 100 KB payload limit")
        if any(str(key).startswith("_") for key in fields):
            raise GovernanceError("CRM field names beginning with underscore are reserved")
        payload = {"lead_id": lead_id, "data": fields, "actor": actor}
        idempotency_key = hashlib.sha256(
            json.dumps({"lead_id": lead_id, "data": fields}, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        event = self.store.enqueue_outbox_event(
            provider="n8n", operation="sync_crm", payload=payload,
            idempotency_key=f"crm-{idempotency_key}",
        )
        self._event(lead_id, lead["campaign_id"], "crm.sync_queued", actor, fields, {"outbox_event_id": event["id"]})
        return {"status": "enqueued", "outbox_event_id": event["id"], "lead_id": lead_id}

    def set_kill_switch(self, enabled: bool, *, actor: str, reason: str) -> dict:
        if actor not in {"jarvis", self.founder_id} or not reason.strip():
            raise GovernanceError("JARVIS or the founder must provide a kill-switch reason")
        self.store.set_control("acquisition_kill_switch", "on" if enabled else "off", actor)
        self.store.audit(actor, "set_kill_switch", "pipeline", "client_acquisition", "allowed",
                         {"enabled": enabled, "reason": reason})
        return {"enabled": enabled, "actor": actor, "reason": reason.strip()}

    def dashboard(self) -> dict:
        leads = self.store.list_leads(limit=5000)
        messages = self.store.list_messages()
        active = [lead for lead in leads if LeadStage(lead["stage"]) not in TERMINAL_STAGES]
        return {
            "kill_switch": self.store.get_control("acquisition_kill_switch", "off") == "on",
            "campaigns": len(self.store.list_campaigns()), "leads": len(leads),
            "qualified": sum(lead["total_score"] >= 70 for lead in leads),
            "active_pipeline_value_cents": sum(lead["estimated_value_cents"] for lead in active),
            "awaiting_approval": sum(message["status"] == "awaiting_approval" for message in messages),
            "sent": sum(message["status"] == "sent" for message in messages),
            "opted_out": sum(lead["do_not_contact"] for lead in leads),
            "stages": {stage.value: sum(lead["stage"] == stage.value for lead in leads) for stage in LeadStage},
        }

    def _require_running(self, operation: str) -> None:
        if self.store.get_control("acquisition_kill_switch", "off") == "on":
            raise GovernanceError(f"Client-acquisition kill switch blocks {operation}")

    def _event(self, lead_id: str | None, campaign_id: str | None, event_type: str, agent: str,
               input_data: object, output: dict) -> None:
        encoded = json.dumps(input_data, sort_keys=True, default=str).encode()
        self.store.publish_pipeline_event(lead_id=lead_id, campaign_id=campaign_id, event_type=event_type,
                                          agent=agent, input_hash=hashlib.sha256(encoded).hexdigest(), output=output)


__all__ = ["AcquisitionPipeline", "LeadStage", "SCORE_LIMITS", "normalize_domain"]
