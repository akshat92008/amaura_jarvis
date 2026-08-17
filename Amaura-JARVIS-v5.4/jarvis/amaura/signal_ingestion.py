"""Safe external-to-company signal ingestion for the canonical v7 runtime.

This layer is intentionally read-mostly. It may observe configured provider
inboxes/workspaces and convert durable inbound facts into existing
``company_signals``; it never sends replies, marks messages read, publishes
content, spends money, dispatches workflows, or grants itself new authority.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import urlencode

from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.inbox import GmailInboxAdapter, InboxService
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_bytes

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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
        github_transport=request_bytes,
    ) -> None:
        self.control = control
        self.company = company or CompanyAutonomyEngine(control)
        self.inbox = inbox or InboxService(control.store, control.founder_id)
        self.gmail_factory = gmail_factory
        self.github_transport = github_transport

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
            return self._deferred("gmail", exc)

    @staticmethod
    def _github_repositories() -> list[str]:
        raw = os.environ.get("AMAURA_V7_GITHUB_SIGNAL_REPOS", "")
        repositories: list[str] = []
        for value in raw.split(","):
            repo = value.strip()
            if repo and _REPO_PATTERN.fullmatch(repo):
                repositories.append(repo)
        return list(dict.fromkeys(repositories))[:25]

    @staticmethod
    def _github_signal(labels: set[str]) -> tuple[str, str] | None:
        lowered = {label.strip().lower() for label in labels}
        if lowered & {"security", "security-incident", "vulnerability"}:
            return "security_incident", "critical"
        if lowered & {"ci", "build", "build-failure", "bug"}:
            return "build_failure", "high"
        if lowered & {"release-ready", "release_ready"}:
            return "release_ready", "medium"
        if lowered & {"revenue", "sales", "customer"}:
            return "revenue_signal", "medium"
        if lowered & {"research", "opportunity", "market"}:
            return "research_opportunity", "medium"
        if "amaura-signal" in lowered:
            return "customer_feedback", "medium"
        return None

    def poll_github(self, *, max_results: int | None = None) -> dict[str, Any]:
        """Read labelled open GitHub issues and convert only explicit signals."""
        if not self._enabled():
            return {"status": "disabled", "provider": "github", "issues": 0, "signals": []}
        token = os.environ.get("AMAURA_GITHUB_TOKEN", "").strip()
        repositories = self._github_repositories()
        if not token or not repositories:
            return {"status": "not_configured", "provider": "github", "issues": 0, "signals": []}
        limit = max_results
        if limit is None:
            limit = int(os.environ.get("AMAURA_V7_GITHUB_SIGNAL_LIMIT", "25"))
        limit = max(1, min(int(limit), 100))
        observed = 0
        signals: list[dict[str, Any]] = []
        try:
            for repository in repositories:
                params = urlencode(
                    {
                        "state": "open",
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": limit,
                    }
                )
                status, raw, _headers = self.github_transport(
                    f"https://api.github.com/repos/{repository}/issues?{params}",
                    method="GET",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=30,
                    max_response_bytes=2_000_000,
                )
                if status != 200:
                    raise GovernanceError(f"GitHub issue observation failed with HTTP {status}")
                decoded = json.loads(raw.decode("utf-8"))
                if not isinstance(decoded, list):
                    raise GovernanceError("GitHub issue observation returned an invalid payload")
                for issue in decoded[:limit]:
                    if not isinstance(issue, dict) or issue.get("pull_request"):
                        continue
                    observed += 1
                    labels = {
                        str(item.get("name") or "") if isinstance(item, dict) else str(item)
                        for item in (issue.get("labels") or [])
                    }
                    mapped = self._github_signal(labels)
                    if mapped is None:
                        continue
                    signal_type, severity = mapped
                    number = str(issue.get("number") or "")
                    updated_at = str(issue.get("updated_at") or "")
                    signal = self.company.ingest_signal(
                        signal_type=signal_type,
                        source=f"github:{repository}",
                        severity=severity,
                        idempotency_key=f"v7:github:{repository}:{number}:{updated_at}",
                        payload={
                            "summary": str(issue.get("title") or "GitHub issue")[:500],
                            "repository": repository,
                            "issue_number": number,
                            "url": str(issue.get("html_url") or "")[:1000],
                            "labels": sorted(label for label in labels if label)[:30],
                            "updated_at": updated_at,
                            # Issue bodies are untrusted external text and are not
                            # copied into an executable company signal.
                        },
                        actor="jarvis",
                    )
                    signals.append(signal)
            self.control.store.set_control("v7.signal_ingestion.github.last_success", datetime.now(UTC).isoformat(), "jarvis")
            return {
                "status": "ok",
                "provider": "github",
                "repositories": repositories,
                "issues": observed,
                "signals": [item["id"] for item in signals],
            }
        except (GovernanceError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return self._deferred("github", exc)

    def _deferred(self, provider: str, exc: Exception) -> dict[str, Any]:
        details = {
            "provider": provider,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
        }
        self.control.store.publish_event("company.signal_ingestion.failed", provider, details)
        self.control.store.audit("jarvis", "ingest_external_signal", "provider", provider, "deferred", details)
        noun = "issues" if provider == "github" else "messages"
        return {"status": "deferred", **details, noun: 0, "signals": []}

    def poll(self) -> dict[str, Any]:
        """Run one bounded external observation cycle."""
        gmail = self.poll_gmail()
        github = self.poll_github()
        components = (gmail, github)
        partial = any(item.get("status") == "deferred" for item in components)
        return {
            "status": "partial" if partial else "ok",
            "gmail": gmail,
            "github": github,
            "signal_count": sum(len(item.get("signals") or []) for item in components),
        }


__all__ = ["SignalIngestionEngine"]
