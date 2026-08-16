"""Durable inbound-message ingestion, classification and founder-reviewed replies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any, cast
from urllib.parse import quote, urlencode

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_json
from jarvis.amaura.oauth import OAuthTokenProvider
from jarvis.amaura.pipeline import AcquisitionPipeline, LeadStage
from jarvis.amaura.store import CompanyStore


def _b64url(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode())
    except Exception as exc:
        raise GovernanceError("Inbound message contained invalid base64url data") from exc


def _plain_from_part(part: dict[str, Any]) -> str:
    mime = str(part.get("mimeType", "")).lower()
    body = cast(dict[str, Any], part.get("body")) if isinstance(part.get("body"), dict) else {}
    data = str(body.get("data", ""))
    if data and mime in {"text/plain", "text/html"}:
        decoded = _b64url(data).decode("utf-8", errors="replace")
        if mime == "text/html":
            decoded = re.sub(r"<style\b[^>]*>.*?</style>|<script\b[^>]*>.*?</script>", " ", decoded, flags=re.I | re.S)
            decoded = re.sub(r"<[^>]+>", " ", decoded)
            decoded = html.unescape(decoded)
        return re.sub(r"\s+", " ", decoded).strip()
    for child in part.get("parts", []) if isinstance(part.get("parts"), list) else []:
        if isinstance(child, dict):
            text = _plain_from_part(child)
            if text:
                return text
    return ""


@dataclass(frozen=True, slots=True)
class InboundMessage:
    provider: str
    external_id: str
    thread_id: str
    sender: str
    recipient: str
    subject: str
    body: str
    received_at: str
    raw_metadata: dict[str, Any]

    def to_record(self, *, lead_id: str = "") -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = "inb_" + hashlib.sha256(f"{self.provider}:{self.external_id}".encode()).hexdigest()[:20]
        payload["lead_id"] = lead_id or None
        payload["content_hash"] = hashlib.sha256(self.body.encode()).hexdigest()
        payload["status"] = "new"
        payload["classification"] = {}
        return payload


class GmailInboxAdapter:
    list_endpoint = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

    def __init__(self, *, token_provider: OAuthTokenProvider | None = None, transport=request_json) -> None:
        self.tokens = token_provider or OAuthTokenProvider("AMAURA_GMAIL")
        self.transport = transport

    @property
    def configured(self) -> bool:
        return self.tokens.configured

    def _call(self, url: str) -> tuple[int, dict[str, Any], dict[str, str]]:
        def attempt(token: str):
            return self.transport(url, method="GET", headers={"Authorization": f"Bearer {token}"}, timeout=30)

        return self.tokens.request_with_refresh(attempt)

    def list_messages(self, *, query: str = "is:unread", max_results: int = 25) -> list[InboundMessage]:
        """Return up to ``max_results`` Gmail messages across all result pages.

        Gmail limits each listing response to 100 messages.  The previous
        implementation read only the first page, which allowed old unread mail
        to starve newer replies indefinitely.  We intentionally keep this
        method bounded while following ``nextPageToken`` until the requested
        cap is reached.
        """
        if not self.configured:
            raise GovernanceError("Gmail inbox OAuth is not configured")
        cap = max(1, min(int(max_results), 500))
        refs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page_token = ""
        while len(refs) < cap:
            params: dict[str, Any] = {
                "q": query,
                "maxResults": min(100, cap - len(refs)),
            }
            if page_token:
                params["pageToken"] = page_token
            url = f"{self.list_endpoint}?{urlencode(params)}"
            status, response, _ = self._call(url)
            if status != 200:
                raise GovernanceError(f"Gmail message listing failed with HTTP {status}")
            page_refs = cast(list[Any], response.get("messages")) if isinstance(response.get("messages"), list) else []
            for ref in page_refs:
                if not isinstance(ref, dict):
                    continue
                external_id = str(ref.get("id", "")).strip()
                if external_id and external_id not in seen_ids:
                    refs.append(ref)
                    seen_ids.add(external_id)
                    if len(refs) >= cap:
                        break
            next_token = str(response.get("nextPageToken", "")).strip()
            if not next_token or next_token == page_token or not page_refs:
                break
            page_token = next_token

        messages: list[InboundMessage] = []
        for ref in refs[:cap]:
            external_id = str(ref.get("id", "")).strip() if isinstance(ref, dict) else ""
            if not external_id:
                continue
            status, raw, _ = self._call(f"{self.list_endpoint}/{quote(external_id, safe='')}?format=full")
            if status != 200:
                continue
            payload = cast(dict[str, Any], raw.get("payload")) if isinstance(raw.get("payload"), dict) else {}
            headers = cast(list[Any], payload.get("headers")) if isinstance(payload.get("headers"), list) else []
            values = {str(v.get("name", "")).lower(): str(v.get("value", "")) for v in headers if isinstance(v, dict)}
            sender = parseaddr(values.get("from", ""))[1] or values.get("from", "")
            recipient = parseaddr(values.get("to", ""))[1] or values.get("to", "")
            body = _plain_from_part(payload) or str(raw.get("snippet", "")).strip()
            internal_ms = str(raw.get("internalDate", ""))
            try:
                received = datetime.fromtimestamp(int(internal_ms) / 1000, tz=UTC).isoformat()
            except (TypeError, ValueError, OSError):
                received = datetime.now(UTC).isoformat()
            messages.append(
                InboundMessage(
                    provider="gmail",
                    external_id=external_id,
                    thread_id=str(raw.get("threadId", "")),
                    sender=sender.strip().lower(),
                    recipient=recipient.strip().lower(),
                    subject=values.get("subject", "").strip(),
                    body=body[:100_000],
                    received_at=received,
                    raw_metadata={
                        "labelIds": raw.get("labelIds", []),
                        "message_id_header": values.get("message-id", ""),
                        "history_id": str(raw.get("historyId", "")),
                    },
                )
            )
        return messages

    def mark_read(self, external_id: str) -> None:
        """Acknowledge a durably stored Gmail message by removing ``UNREAD``."""
        clean_id = external_id.strip()
        if not clean_id:
            raise GovernanceError("Gmail message id is required")

        def attempt(token: str):
            return self.transport(
                f"{self.list_endpoint}/{quote(clean_id, safe='')}/modify",
                method="POST",
                payload={"removeLabelIds": ["UNREAD"]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )

        status, _response, _headers = self.tokens.request_with_refresh(attempt)
        if status != 200:
            raise GovernanceError(f"Gmail message acknowledgement failed with HTTP {status}")


class ReplyClassifier:
    _rules = [
        # Safety-critical negative intent must be evaluated before positive
        # keywords.  In particular, "not interested" contains "interested".
        (
            "opt_out",
            (
                r"^\s*stop[.!]?\s*$",
                r"\b(?:please\s+)?stop(?:\s+(?:emailing|messaging|contacting|sending))?(?:\s+me)?\b",
                r"\bunsubscribe\b",
                r"\bopt[ -]?out\b",
                r"\bremove me\b",
                r"\btake me off\b",
                r"\bdo not (?:contact|email|message|call) me\b",
                r"\bdon'?t (?:contact|email|message|call) me\b",
                r"\bno more (?:emails?|messages?|calls?|contact)\b",
            ),
            0.995,
        ),
        (
            "not_interested",
            (
                r"\bnot(?:\s+(?:currently|really|particularly|remotely|at all))?\s+interested\b",
                r"\bno thanks\b",
                r"\bno thank you\b",
                r"\bnot a fit\b",
                r"\bwe(?:'re| are) not looking\b",
            ),
            0.96,
        ),
        ("wrong_contact", (r"\bwrong (person|contact)\b", r"\bno longer work\b"), 0.94),
        ("not_now", (r"\bnot now\b", r"\blater\b", r"\bnext (month|quarter|year)\b"), 0.86),
        (
            "interested",
            (
                r"\binterested\b",
                r"\blet'?s talk\b",
                r"\bschedule (a )?(call|meeting)\b",
                r"\bsend (me )?(details|proposal)\b",
            ),
            0.90,
        ),
        ("price_objection", (r"\btoo expensive\b", r"\bbudget\b", r"\bprice\b", r"\bcost\b"), 0.80),
        (
            "needs_information",
            (r"\bhow does\b", r"\bcan you explain\b", r"\bmore (information|details)\b", r"\bwhat do you\b"),
            0.78,
        ),
    ]

    def classify(self, text: str) -> dict[str, Any]:
        clean = re.sub(r"\s+", " ", text.lower()).strip()
        for label, patterns, confidence in self._rules:
            matched = [pattern for pattern in patterns if re.search(pattern, clean)]
            if matched:
                return {
                    "label": label,
                    "confidence": confidence,
                    "matched_rules": matched,
                    "requires_founder_review": True,
                }
        return {"label": "unclear", "confidence": 0.35, "matched_rules": [], "requires_founder_review": True}


class InboxService:
    def __init__(
        self, store: CompanyStore, founder_id: str = "founder", classifier: ReplyClassifier | None = None
    ) -> None:
        self.store = store
        self.founder_id = founder_id
        self.pipeline = AcquisitionPipeline(store, founder_id)
        self.classifier = classifier or ReplyClassifier()

    def ingest(self, message: InboundMessage) -> tuple[dict[str, Any], bool]:
        lead = self.store.get_lead_by_public_contact(message.sender)
        record, inserted = self.store.upsert_inbound_message(message.to_record(lead_id=lead["id"] if lead else ""))
        if inserted:
            self.store.publish_event(
                "inbox.message.received",
                record["id"],
                {"provider": record["provider"], "lead_id": record.get("lead_id") or ""},
            )
            self.store.audit(
                "jarvis",
                "ingest_inbound_message",
                "inbound_message",
                record["id"],
                "stored",
                {"provider": record["provider"], "external_id": record["external_id"]},
            )
        return record, inserted

    def sync_gmail(
        self,
        adapter: GmailInboxAdapter | None = None,
        *,
        max_results: int = 25,
        query: str = "is:unread",
        mark_read: bool = True,
    ) -> list[dict[str, Any]]:
        client = adapter or GmailInboxAdapter()
        inserted: list[dict[str, Any]] = []
        acknowledged = 0
        acknowledgement_failures: list[dict[str, str]] = []
        highest_history_id = 0
        for message in client.list_messages(query=query, max_results=max_results):
            record, created = self.ingest(message)
            if created:
                inserted.append(record)
            history_id = str(message.raw_metadata.get("history_id", ""))
            if history_id.isdigit():
                highest_history_id = max(highest_history_id, int(history_id))
            if mark_read:
                try:
                    client.mark_read(message.external_id)
                    acknowledged += 1
                except GovernanceError as exc:
                    acknowledgement_failures.append({"external_id": message.external_id, "error": str(exc)})
                    self.store.audit(
                        "jarvis",
                        "acknowledge_inbound_message",
                        "inbound_message",
                        record["id"],
                        "failed",
                        {"provider": "gmail", "error": str(exc)},
                    )
        self.store.set_integration_cursor(
            "gmail",
            str(highest_history_id) if highest_history_id else "",
            {
                "query": query,
                "requested_limit": max_results,
                "inserted": len(inserted),
                "acknowledged": acknowledged,
                "acknowledgement_failures": acknowledgement_failures,
                "synced_at": datetime.now(UTC).isoformat(),
            },
        )
        return inserted

    @staticmethod
    def _reply_draft(classification: str, sender: str, subject: str) -> tuple[str, str]:
        name = sender.split("@", 1)[0].replace(".", " ").title() if "@" in sender else "there"
        subject_value = f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject
        if classification == "interested":
            body = f"Hi {name},\n\nThank you for getting back to me. I’d be glad to understand your current process and the outcome you want. Could you share the main bottleneck and a suitable time for a short discussion?\n\nBest,\nAkshat"
        elif classification == "price_objection":
            body = f"Hi {name},\n\nThanks for the honest feedback. Before suggesting a lower-cost option, I’d like to confirm which outcome matters most and what budget range would be practical. I can then propose a narrower scope without making commitments before review.\n\nBest,\nAkshat"
        elif classification == "needs_information":
            body = f"Hi {name},\n\nThanks for your reply. I can share a concise breakdown tailored to your current workflow. Which part would be most useful: lead capture, follow-up automation, CRM visibility, or a custom requirement?\n\nBest,\nAkshat"
        else:
            body = f"Hi {name},\n\nThank you for your response. I’ve reviewed your message and will follow up with the most relevant next step after confirming the details.\n\nBest,\nAkshat"
        return subject_value, body

    def process(self, inbound_id: str, *, stage_reply: bool = True) -> dict[str, Any]:
        record = self.store.get_inbound_message(inbound_id)
        if record["status"] in {"processed", "opted_out"}:
            return record
        classification = self.classifier.classify(record["body"])
        lead = self.store.get_lead(record["lead_id"]) if record.get("lead_id") else None
        status = "processed"
        reply_message_id = ""
        if lead and classification["label"] in {"opt_out", "not_interested"}:
            reason = (
                "Inbound opt-out request"
                if classification["label"] == "opt_out"
                else "Inbound rejection: not interested"
            )
            try:
                self.pipeline.transition(lead["id"], LeadStage.OPTED_OUT, actor="reply_classifier", reason=reason)
            except GovernanceError:
                self.store.update_lead(
                    lead["id"],
                    do_not_contact=True,
                    opt_out_reason=reason,
                    next_action="",
                    next_action_at=None,
                )
            status = "opted_out"
        elif lead:
            try:
                if LeadStage(lead["stage"]) in {LeadStage.SENT, LeadStage.FOLLOWUP_DUE}:
                    self.pipeline.transition(
                        lead["id"], LeadStage.REPLIED, actor="reply_classifier", reason="Inbound reply received"
                    )
            except (GovernanceError, ValueError):
                pass
            if stage_reply and classification["label"] not in {"not_interested", "wrong_contact", "not_now"}:
                subject, body = self._reply_draft(classification["label"], record["sender"], record["subject"])
                channel = "email" if record["provider"] == "gmail" else record["provider"]
                message = self.pipeline.stage_message(
                    lead["id"],
                    recipient=record["sender"],
                    channel=channel,
                    message_type="reply",
                    subject=subject,
                    body=body,
                    actor="reply_writer",
                )
                reply_message_id = message["id"]
        updated = self.store.update_inbound_message(
            inbound_id, status=status, classification={**classification, "reply_message_id": reply_message_id}
        )
        self.store.publish_event(
            "inbox.message.processed",
            inbound_id,
            {"classification": classification["label"], "reply_message_id": reply_message_id},
        )
        return updated


def verify_meta_signature(body: bytes, signature_header: str, app_secret: str | None = None) -> None:
    secret = (app_secret if app_secret is not None else os.environ.get("AMAURA_META_APP_SECRET", "")).encode()
    if len(secret) < 16:
        raise GovernanceError("Meta webhook secret is not configured")
    supplied = signature_header.removeprefix("sha256=").strip().lower()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise GovernanceError("Meta webhook signature is invalid")


def parse_meta_webhook(payload: dict[str, Any]) -> list[InboundMessage]:
    results: list[InboundMessage] = []
    for entry in payload.get("entry", []) if isinstance(payload.get("entry"), list) else []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) if isinstance(entry.get("changes"), list) else []:
            if not isinstance(change, dict):
                continue
            value = cast(dict[str, Any], change.get("value")) if isinstance(change.get("value"), dict) else {}
            metadata = cast(dict[str, Any], value.get("metadata")) if isinstance(value.get("metadata"), dict) else {}
            contacts = cast(list[Any], value.get("contacts")) if isinstance(value.get("contacts"), list) else []
            names = {
                str(c.get("wa_id", "")): str(cast(dict[str, Any], c.get("profile")).get("name", ""))
                for c in contacts
                if isinstance(c, dict) and isinstance(c.get("profile"), dict)
            }
            for msg in cast(list[Any], value.get("messages")) if isinstance(value.get("messages"), list) else []:
                if not isinstance(msg, dict):
                    continue
                text = cast(dict[str, Any], msg.get("text")) if isinstance(msg.get("text"), dict) else {}
                body = str(text.get("body", "")).strip()
                if not body:
                    continue
                sender = str(msg.get("from", "")).strip()
                received = (
                    datetime.fromtimestamp(int(msg.get("timestamp", 0)), tz=UTC).isoformat()
                    if str(msg.get("timestamp", "")).isdigit()
                    else datetime.now(UTC).isoformat()
                )
                results.append(
                    InboundMessage(
                        provider="whatsapp",
                        external_id=str(msg.get("id", "")),
                        thread_id=sender,
                        sender=sender,
                        recipient=str(metadata.get("display_phone_number", "")),
                        subject="",
                        body=body,
                        received_at=received,
                        raw_metadata={"contact_name": names.get(sender, ""), "type": msg.get("type", "")},
                    )
                )
        for messaging in cast(list[Any], entry.get("messaging")) if isinstance(entry.get("messaging"), list) else []:
            if not isinstance(messaging, dict):
                continue
            message = (
                cast(dict[str, Any], messaging.get("message")) if isinstance(messaging.get("message"), dict) else {}
            )
            text = str(message.get("text", "")).strip()
            external_id = str(message.get("mid", "")).strip()
            if not text or not external_id:
                continue
            sender_data = (
                cast(dict[str, Any], messaging.get("sender")) if isinstance(messaging.get("sender"), dict) else {}
            )
            recipient_data = (
                cast(dict[str, Any], messaging.get("recipient")) if isinstance(messaging.get("recipient"), dict) else {}
            )
            sender = str(sender_data.get("id", ""))
            recipient = str(recipient_data.get("id", ""))
            provider = "instagram" if str(payload.get("object", "")).lower() == "instagram" else "facebook"
            timestamp = messaging.get("timestamp")
            try:
                if timestamp is None:
                    raise ValueError("missing timestamp")
                received = datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC).isoformat()
            except (TypeError, ValueError, OSError):
                received = datetime.now(UTC).isoformat()
            results.append(
                InboundMessage(
                    provider=provider,
                    external_id=external_id,
                    thread_id=sender,
                    sender=sender,
                    recipient=recipient,
                    subject="",
                    body=text,
                    received_at=received,
                    raw_metadata={"object": payload.get("object", "")},
                )
            )
    return results


__all__ = [
    "GmailInboxAdapter",
    "InboundMessage",
    "InboxService",
    "ReplyClassifier",
    "parse_meta_webhook",
    "verify_meta_signature",
]
