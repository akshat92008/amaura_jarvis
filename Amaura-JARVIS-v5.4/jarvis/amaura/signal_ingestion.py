"""Safe external-to-company signal ingestion for the canonical v7 runtime.

This layer is intentionally read-mostly. It may observe configured provider
inboxes and convert durable inbound facts into existing ``company_signals``;
it never sends replies, marks messages read, publishes content, spends money,
or grants itself new authority.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Callable

from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.inbox import GmailInboxAdapter, InboxService
from jarvis.amaura.models import GovernanceError


class SignalIngestionEngine:
    """Normalize configured external observations into durable company signals."""

    _REVENUE_LABELS = {"interested", "price_objection", "needs_information"}
    _FEEDBACK_LABELS = {"not_interested", "not_now", "wrong_contact", "opt_out", "unclear"}

    def __init__(
        self,
        control: AmauraControlPlane,
        *,
        company: CompanyAutonomyEngine | None = None,
        inbox: InboxService | None = None,
        gmail_factory: Callable[[], GmailInboxAdapter] = GmailInboxAdapter,
    ) -> None:
        self.control = control
        self.company = company or CompanyAutonomyEngine(control)
        self.inbox = inbox or InboxService(control.store, control.founder_id)
        self.gmail_factory = gmail_factory

    @staticmethod
    def _enabled() -> bool:
        return os.environ.get("AMAURA_V7_EXTERNAL_SIGNAL_INGESTION", "1").strip().lower() not in {
            "0",
            "false",
            "off",
            "disabled",
        }

    def _signal_from_inbound(self, record: dict[str, Any]) -> dict[str, Any] | None:
        classification = dict(record.get("classification") or {})
        label = str(classification.get("label") or "unclear")
        if label in self._REVENUE_LABELS:
            signal_type = "revenue_signal"
            severity = "high" if label == "interested" else "medium"
        elif label in self._FEEDBACK_LABELS:
            signal_type = "customer_feedback"
            severity = "medium" if label in {"opt_out", "not_interested"} else "low"
        else:
            return None

        return self.company.ingest_signal(
            signal_type=signal_type,
            source=f"inbox:{record.get('provider') or 'unknown'}",
            severity=severity,
            idempotency_key=f"v7:inbound:{record['id']}:{label}",
            payload={
                "summary": f"Inbound {record.get('provider') or 'message'} classified as {label}",
                "inbound_id": record["id"],
                "lead_id": str(record.get("lead_id") or ""),
                "classification": classification,
                "subject": str(record.get("subject") or "")[:500],
                # Deliberately omit the message body from the company signal.
                # The canonical inbound record remains available under its
                # original authorization boundary if a later task needs it.
                "received_at": str(record.get("received_at") or ""),
            },
            actor="jarvis",
        )

    def poll_gmail(self, *, max_results: int | None = None) -> dict[str, Any]:
        """Observe unread Gmail without acknowledging or sending anything."""
        if not self._enabled():
            return {"status": "disabled", "provider": "gmail", "messages": 0, "signals": []}
        adapter = self.gmail_factory()
        if not adapter.configured:
            return {"status": "not_configured", "provider": "gmail", "messages": 0, "signals": []}

        limit = max_results
        if limit is None:
            limit = int(os.environ.get("AMAURA_V7_GMAIL_SIGNAL_LIMIT", "25"))
        limit = max(1, min(int(limit), 100))
        inserted = 0
        processed = 0
        signals: list[dict[str, Any]] = []

        try:
            messages = adapter.list_messages(query="is:unread", max_results=limit)
            for message in messages:
                record, created = self.inbox.ingest(message)
                if created:
                    inserted += 1
                # Classification and CRM stage changes are internal and
                # governed. stage_reply=False is essential: observation must
                # never stage an outbound message by itself.
                updated = self.inbox.process(record["id"], stage_reply=False)
                processed += 1
                signal = self._signal_from_inbound(updated)
                if signal is not None:
                    signals.append(signal)
            self.control.store.set_control("v7.signal_ingestion.gmail.last_success", datetime.now(UTC).isoformat(), "jarvis")
            return {
                "status": "ok",
                "provider": "gmail",
                "messages": len(messages),
                "inserted": inserted,
                "processed": processed,
                "signals": [item["id"] for item in signals],
            }
        except (GovernanceError, OSError, RuntimeError, ValueError) as exc:
            details = {
                "provider": "gmail",
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
            }
            self.control.store.publish_event("company.signal_ingestion.failed", "gmail", details)
            self.control.store.audit("jarvis", "ingest_external_signal", "provider", "gmail", "deferred", details)
            return {"status": "deferred", **details, "messages": 0, "signals": []}

    def poll(self) -> dict[str, Any]:
        """Run one bounded external observation cycle."""
        gmail = self.poll_gmail()
        return {
            "status": "ok" if gmail.get("status") in {"ok", "not_configured", "disabled"} else "partial",
            "gmail": gmail,
            "signal_count": len(gmail.get("signals") or []),
        }


__all__ = ["SignalIngestionEngine"]
