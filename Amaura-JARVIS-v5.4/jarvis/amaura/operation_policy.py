"""Authoritative risk policy for durable provider operations.

All code paths that retry, recover, reconcile, or certify provider operations
must consult this registry.  Unknown outbox operations fail closed and require
human reconciliation after an ambiguous attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    operation: str
    external_side_effect: bool
    retry_after_definite_rejection: bool
    lease_expiry_requires_reconciliation: bool
    verified_receipt_required: bool


_POLICIES: Final[dict[str, OperationPolicy]] = {
    "send_email": OperationPolicy("send_email", True, True, True, True),
    "send_imessage": OperationPolicy("send_imessage", True, False, True, True),
    "sync_crm": OperationPolicy("sync_crm", True, True, True, True),
    "create_private_draft": OperationPolicy("create_private_draft", True, True, True, True),
    "publish_content": OperationPolicy("publish_content", True, False, True, True),
    "prepare_assisted_message": OperationPolicy("prepare_assisted_message", False, True, False, True),
    "send_telegram_notification": OperationPolicy("send_telegram_notification", True, True, True, True),
    "create_calendar_event": OperationPolicy("create_calendar_event", True, False, True, True),
    "upload_drive_file": OperationPolicy("upload_drive_file", True, False, True, True),
    "create_github_issue": OperationPolicy("create_github_issue", True, False, True, True),
    "dispatch_github_workflow": OperationPolicy("dispatch_github_workflow", True, False, True, True),
    "publish_linkedin_text": OperationPolicy("publish_linkedin_text", True, False, True, True),
    "publish_facebook_text": OperationPolicy("publish_facebook_text", True, False, True, True),
    "publish_instagram_media": OperationPolicy("publish_instagram_media", True, False, True, True),
    "capture_analytics_event": OperationPolicy("capture_analytics_event", True, True, True, True),
    "run_nexus_delivery": OperationPolicy("run_nexus_delivery", True, False, True, True),
    "run_noryx_delivery": OperationPolicy("run_noryx_delivery", True, False, True, True),
}

_UNKNOWN_POLICY: Final[OperationPolicy] = OperationPolicy(
    operation="unknown",
    external_side_effect=True,
    retry_after_definite_rejection=False,
    lease_expiry_requires_reconciliation=True,
    verified_receipt_required=True,
)


def operation_policy(operation: str) -> OperationPolicy:
    """Return the registered policy, failing closed for unknown operations."""
    normalized = str(operation or "").strip().lower()
    return _POLICIES.get(normalized, _UNKNOWN_POLICY)


def known_operations() -> frozenset[str]:
    return frozenset(_POLICIES)


def requires_reconciliation_after_lease_expiry(operation: str) -> bool:
    return operation_policy(operation).lease_expiry_requires_reconciliation


__all__ = [
    "OperationPolicy",
    "known_operations",
    "operation_policy",
    "requires_reconciliation_after_lease_expiry",
]
