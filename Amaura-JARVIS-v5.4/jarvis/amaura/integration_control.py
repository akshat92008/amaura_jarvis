"""Founder-approved durable integration action control plane."""

from __future__ import annotations

import uuid
from typing import Any

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.store import CompanyStore

_ALLOWED: dict[tuple[str, str], str] = {
    ("assisted-browser", "prepare_assisted_message"): "medium",
    ("telegram", "send_telegram_notification"): "medium",
    ("google-calendar", "create_calendar_event"): "medium",
    ("google-drive", "upload_drive_file"): "medium",
    ("github", "create_github_issue"): "medium",
    ("github", "dispatch_github_workflow"): "high",
    ("linkedin", "publish_linkedin_text"): "high",
    ("facebook", "publish_facebook_text"): "high",
    ("instagram", "publish_instagram_media"): "high",
    ("posthog", "capture_analytics_event"): "low",
    ("nexus", "run_nexus_delivery"): "high",
    ("noryx", "run_noryx_delivery"): "high",
}

_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class IntegrationActionController:
    def __init__(self, store: CompanyStore, founder_id: str = "founder") -> None:
        self.store = store
        self.founder_id = founder_id

    def stage(
        self,
        *,
        provider: str,
        operation: str,
        payload: dict[str, Any],
        requested_by: str = "jarvis",
        risk: str | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        key = (provider.strip().lower(), operation.strip().lower())
        if key not in _ALLOWED:
            raise GovernanceError("Integration provider/operation is not allowlisted")
        minimum_risk = _ALLOWED[key]
        resolved_risk = (risk or minimum_risk).strip().lower()
        if resolved_risk not in _RISK_RANK:
            raise GovernanceError("Invalid integration action risk")
        if _RISK_RANK[resolved_risk] < _RISK_RANK[minimum_risk]:
            raise GovernanceError(f"Integration action risk cannot be lower than {minimum_risk} for {key[0]}/{key[1]}")
        if not isinstance(payload, dict) or not payload:
            raise GovernanceError("Integration action payload is required")
        action_id = "iact_" + uuid.uuid4().hex[:16]
        idem = idempotency_key.strip() or f"integration:{provider}:{operation}:{self.store.canonical_hash(payload)}"
        action, inserted = self.store.insert_integration_action(
            {
                "id": action_id,
                "provider": key[0],
                "operation": key[1],
                "payload": payload,
                "payload_hash": self.store.canonical_hash(payload),
                "idempotency_key": idem,
                "risk": resolved_risk,
                "status": "awaiting_approval",
                "requested_by": requested_by,
            }
        )
        if inserted:
            self.store.publish_event(
                "integration.action.awaiting_approval",
                action["id"],
                {"provider": key[0], "operation": key[1], "risk": resolved_risk},
            )
            self.store.audit(
                requested_by,
                "stage_integration_action",
                "integration_action",
                action["id"],
                "awaiting_approval",
                {"provider": key[0], "operation": key[1], "risk": resolved_risk},
            )
        return action

    def decide(self, action_id: str, *, approve: bool, actor: str, reason: str = "") -> dict[str, Any]:
        if actor != self.founder_id:
            raise GovernanceError("Only the founder may approve integration actions")
        if approve and self.store.get_control("external_actions_kill_switch", "off").strip().lower() == "on":
            raise GovernanceError("External actions are disabled by the founder kill switch")
        if not approve:
            with self.store.atomic_block():
                action = self.store.approve_integration_action(action_id, actor=actor, approved=False, reason=reason)
                self.store.audit(
                    actor,
                    "reject_integration_action",
                    "integration_action",
                    action_id,
                    "rejected",
                    {"reason": reason},
                )
            return action
        with self.store.atomic_block():
            action, event = self.store.approve_and_enqueue_integration_action(action_id, actor=actor, reason=reason)
            self.store.publish_event("integration.action.enqueued", action_id, {"outbox_event_id": event["id"]})
            self.store.audit(
                actor,
                "approve_integration_action",
                "integration_action",
                action_id,
                "enqueued",
                {"outbox_event_id": event["id"], "reason": reason},
            )
        return action

    def list_pending(self) -> list[dict[str, Any]]:
        return self.store.list_integration_actions(status="awaiting_approval")


__all__ = ["IntegrationActionController"]
