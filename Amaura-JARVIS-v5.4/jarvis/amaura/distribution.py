"""Founder-governed distribution scheduling, publishing and analytics feedback."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
import weakref
from datetime import UTC, datetime
from typing import Any

from jarvis.amaura.integrations import ProviderReceipt, verify_provider_receipt
from jarvis.amaura.models import GovernanceError, TaskState

SUPPORTED_PLATFORMS = {
    "youtube",
    "instagram",
    "linkedin",
    "x",
    "github",
    "blog",
}
PUBLICATION_VISIBILITIES = {"private", "draft", "public"}
TERMINAL_PUBLICATION_STATES = {"published", "failed", "cancelled"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _normalise_schedule(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise GovernanceError("Publication schedule must include an explicit timezone")
    return parsed.astimezone(UTC).isoformat()


class DistributionEngine:
    """Create immutable publication packages and execute them only after approval."""

    def __init__(self, control_plane):
        # Keep the controller as a weak proxy.  A strong back-reference creates a
        # ControlPlane -> DistributionEngine -> ControlPlane cycle that delays
        # SQLite cleanup until cyclic GC and can leak descriptors in workers.
        self.control = weakref.proxy(control_plane)
        self.store = control_plane.store
        self.content = control_plane.content_factory
        self.founder_id = control_plane.founder_id

    def _publication_payload(self, publication: dict[str, Any]) -> dict[str, Any]:
        assets = []
        all_assets = {
            asset["id"]: asset
            for asset in self.store.list_content_assets(publication["campaign_id"])
        }
        for asset_id in publication["asset_ids"]:
            if asset_id not in all_assets:
                raise GovernanceError("Publication references an unknown campaign asset")
            asset = all_assets[asset_id]
            assets.append(
                {
                    "id": asset["id"],
                    "type": asset["asset_type"],
                    "uri": asset["uri"],
                    "sha256": asset["sha256"],
                }
            )
        return {
            "publication_id": publication["id"],
            "campaign_id": publication["campaign_id"],
            "platform": publication["platform"],
            "account_ref": publication["account_ref"],
            "visibility": publication["visibility"],
            "title": publication["title"],
            "body": publication["body"],
            "assets": assets,
            "scheduled_at": publication["scheduled_at"],
            "metadata": publication["metadata"],
        }

    def stage_publication(
        self,
        *,
        campaign_id: str,
        platform: str,
        title: str,
        body: str,
        asset_ids: list[str],
        visibility: str = "public",
        scheduled_at: str | None = None,
        account_ref: str = "",
        metadata: dict[str, Any] | None = None,
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor not in {"jarvis", self.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may stage publication")
        platform = platform.strip().lower()
        visibility = visibility.strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise GovernanceError(f"Unsupported publication platform: {platform}")
        if visibility not in PUBLICATION_VISIBILITIES:
            raise GovernanceError("Publication visibility must be private, draft, or public")
        if not title.strip() or not body.strip():
            raise GovernanceError("Publication title and body are required")
        readiness = self.content.publication_readiness(campaign_id)
        if not readiness["ready"]:
            raise GovernanceError(
                "Campaign is not publication-ready: "
                + ", ".join(readiness["missing_approved_asset_types"])
            )
        approved_assets = {
            asset["id"]: asset
            for asset in self.store.list_content_assets(campaign_id)
            if asset["status"] == "approved"
        }
        unique_asset_ids = list(dict.fromkeys(asset_ids))
        if not unique_asset_ids:
            raise GovernanceError("At least one approved content asset is required")
        missing = [asset_id for asset_id in unique_asset_ids if asset_id not in approved_assets]
        if missing:
            raise GovernanceError(
                "Publication may reference only approved campaign assets: " + ", ".join(missing)
            )
        normalised_schedule = _normalise_schedule(scheduled_at)
        publication_id = _id("pub")
        provisional = {
            "id": publication_id,
            "campaign_id": campaign_id,
            "task_id": "",
            "platform": platform,
            "account_ref": account_ref.strip(),
            "visibility": visibility,
            "title": title.strip(),
            "body": body.strip(),
            "asset_ids": unique_asset_ids,
            "payload_hash": "",
            "idempotency_key": "",
            "status": "awaiting_approval" if visibility == "public" else "staged",
            "scheduled_at": normalised_schedule,
            "outbox_event_id": "",
            "external_id": "",
            "provider": "",
            "provider_status": "",
            "error": "",
            "metadata": metadata or {},
        }
        payload = self._publication_payload(provisional)
        payload_hash = self.store.canonical_hash(payload)
        idempotency_key = f"publication:{payload_hash}"
        task_id = _id("task")
        evidence = [
            {
                "type": "content_asset",
                "reference": asset["uri"],
                "sha256": asset["sha256"],
                "success": True,
                "excerpt": f"{asset['asset_type']}:{asset['id']}",
            }
            for asset in approved_assets.values()
            if asset["id"] in unique_asset_ids
        ]
        task = {
            "id": task_id,
            "parent_id": None,
            "item_type": "task",
            "workflow_id": "content_factory",
            "title": f"Approve {platform} publication: {title.strip()[:80]}",
            "description": "Review the exact immutable publication package and authorize external publishing.",
            "owner_id": "publishing",
            "reviewer_id": self.founder_id,
            "state": TaskState.AWAITING_APPROVAL.value if visibility == "public" else TaskState.COMPLETED.value,
            "priority": 2,
            "budget_cents": 0,
            "spent_cents": 0,
            "risk": "high" if visibility == "public" else "medium",
            "action_type": "public_publish" if visibility == "public" else "private_draft",
            "success_metric": "Provider returns a signed receipt for the exact approved payload.",
            "acceptance_criteria": [
                "Campaign publication-readiness passed",
                "All referenced assets are approved and hash-bound",
                "Exact platform payload is founder-visible",
                "Provider idempotency key and receipt are verified",
            ],
            "dependencies": [],
            "evidence": evidence,
            "summary": json.dumps(payload, indent=2, sort_keys=True),
            "metadata": {
                "distribution_job_id": publication_id,
                "campaign_id": campaign_id,
                "payload_hash": payload_hash,
                "workspace": os.getcwd(),
                "inputs": {"campaign_id": campaign_id, "platform": platform},
            },
        }
        provisional.update(
            {
                "task_id": task_id,
                "payload_hash": payload_hash,
                "idempotency_key": idempotency_key,
            }
        )
        with self.store.atomic_block():
            self.store.insert_work_item(task)
            publication = self.store.create_distribution_publication(provisional)
            approval = None
            if visibility == "public":
                approval = self.control._request_approval(task, requested_by=actor)
            self.store.publish_event(
                "distribution.publication.staged",
                publication_id,
                {
                    "campaign_id": campaign_id,
                    "platform": platform,
                    "visibility": visibility,
                    "payload_hash": payload_hash,
                },
            )
            self.store.audit(
                actor,
                "stage_publication",
                "distribution_publication",
                publication_id,
                "awaiting_approval" if visibility == "public" else "staged",
                {"platform": platform, "payload_hash": payload_hash},
            )
        return {"publication": publication, "task": self.store.get_work_item(task_id), "approval": approval}

    def _dispatch_once(
        self, publication_id: str, *, actor: str = "jarvis", now: datetime | None = None
    ) -> tuple[dict[str, Any], bool]:
        if actor not in {"jarvis", self.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may enqueue publication")
        current_time = now or datetime.now(UTC)
        # BEGIN IMMEDIATE serializes the read-check-enqueue-update boundary across
        # all processes sharing the SQLite database. Only the transaction that
        # observes an eligible state is allowed to emit events or audit records.
        with self.store.atomic_block():
            publication = self.store.get_distribution_publication(publication_id)
            if publication["status"] in TERMINAL_PUBLICATION_STATES or publication["status"] == "enqueued":
                return publication, False
            if publication["status"] not in {"awaiting_approval", "staged", "scheduled"}:
                return publication, False
            task = self.store.get_work_item(publication["task_id"])
            if publication["visibility"] == "public" and task["state"] != TaskState.COMPLETED.value:
                raise GovernanceError("Public publication requires completed founder approval")
            current_payload = self._publication_payload(publication)
            current_hash = self.store.canonical_hash(current_payload)
            if current_hash != publication["payload_hash"]:
                raise GovernanceError("Publication package changed after staging")
            if publication["scheduled_at"]:
                scheduled = datetime.fromisoformat(publication["scheduled_at"])
                if current_time < scheduled:
                    return self.store.update_distribution_publication(publication_id, status="scheduled"), False
            operation = "publish_content" if publication["visibility"] == "public" else "create_private_draft"
            provider = "approved-publication" if operation == "publish_content" else "private-publication"
            event = self.store.enqueue_outbox_event(
                provider=provider, operation=operation, payload=current_payload,
                idempotency_key=publication["idempotency_key"],
            )
            updated = self.store.update_distribution_publication(
                publication_id, status="enqueued", outbox_event_id=event["id"], error="",
            )
            self.store.publish_event(
                "distribution.publication.enqueued", publication_id,
                {"outbox_event_id": event["id"], "operation": operation},
            )
            self.store.audit(
                actor, "enqueue_publication", "distribution_publication", publication_id, "allowed",
                {"outbox_event_id": event["id"], "operation": operation},
            )
            return updated, True

    def dispatch(self, publication_id: str, *, actor: str = "jarvis", now: datetime | None = None) -> dict[str, Any]:
        publication, _ = self._dispatch_once(publication_id, actor=actor, now=now)
        return publication

    def dispatch_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 5,
        actor: str = "jarvis",
    ) -> list[dict[str, Any]]:
        """Enqueue approved publications whose schedule is due.

        Unapproved public packages are skipped. Each package remains protected by
        its unique outbox idempotency key, so repeated autopilot ticks are safe.
        """
        current = now or datetime.now(UTC)
        cap = max(1, min(int(limit), 50))
        candidates = self.store.list_distribution_publications(limit=1000)
        dispatched: list[dict[str, Any]] = []
        for publication in reversed(candidates):
            if len(dispatched) >= cap:
                break
            if publication["status"] not in {"awaiting_approval", "staged", "scheduled"}:
                continue
            if publication["scheduled_at"]:
                scheduled = datetime.fromisoformat(publication["scheduled_at"])
                if current < scheduled:
                    continue
            if publication["visibility"] == "public":
                task = self.store.get_work_item(publication["task_id"])
                if task["state"] != TaskState.COMPLETED.value:
                    continue
            result, created = self._dispatch_once(publication["id"], actor=actor, now=current)
            if created:
                dispatched.append(result)
        return dispatched

    def confirm_publication(
        self,
        publication_id: str,
        *,
        provider_receipt: ProviderReceipt | dict[str, Any],
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        publication = self.store.get_distribution_publication(publication_id)
        operation = "publish_content" if publication["visibility"] == "public" else "create_private_draft"
        payload = self._publication_payload(publication)
        receipt = verify_provider_receipt(
            provider_receipt,
            expected_operation=operation,
            expected_idempotency_key=publication["idempotency_key"],
            expected_payload=payload,
        )
        status = "published" if operation == "publish_content" else "draft_created"
        updated = self.store.update_distribution_publication(
            publication_id,
            status=status,
            external_id=receipt.external_id,
            provider=receipt.provider,
            provider_status=receipt.status,
            error="",
        )
        self.store.publish_event(
            f"distribution.publication.{status}",
            publication_id,
            {"provider": receipt.provider, "external_id": receipt.external_id},
        )
        self.store.audit(
            actor,
            "confirm_publication",
            "distribution_publication",
            publication_id,
            status,
            {"provider": receipt.provider, "external_id": receipt.external_id},
        )
        return updated

    def mark_reconciliation_required(self, publication_id: str, error: str) -> dict[str, Any]:
        return self.store.update_distribution_publication(
            publication_id,
            status="reconciliation_required",
            error=error[:4000],
        )

    def record_metrics(
        self,
        publication_id: str,
        *,
        window: str,
        metrics: dict[str, int | float],
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        publication = self.store.get_distribution_publication(publication_id)
        entry = self.content.record_metrics(
            publication["campaign_id"],
            platform=publication["platform"],
            window=window,
            metrics=metrics,
            captured_at=captured_at,
        )
        lesson = self._derive_lesson(publication, window=window, metrics=metrics)
        if lesson:
            self.store.record_content_lesson(
                campaign_id=publication["campaign_id"],
                lesson=lesson,
                evidence_refs=[
                    {
                        "type": "content_metrics",
                        "reference": entry["id"],
                        "window": window,
                        "platform": publication["platform"],
                    }
                ],
            )
        return {"metrics": entry, "lesson": lesson}

    @staticmethod
    def _derive_lesson(
        publication: dict[str, Any],
        *,
        window: str,
        metrics: dict[str, int | float],
    ) -> str:
        impressions = float(metrics.get("impressions", 0) or 0)
        views = float(metrics.get("views", 0) or 0)
        clicks = float(metrics.get("clicks", 0) or 0)
        watch_time = float(metrics.get("watch_time_seconds", 0) or 0)
        ctr = clicks / impressions if impressions else 0.0
        average_watch = watch_time / views if views else 0.0
        if impressions >= 100 and ctr < 0.02:
            return (
                f"{publication['platform']} {window}: CTR is below 2%; test a clearer title, thumbnail, "
                "or opening promise while preserving the verified claim set."
            )
        if views >= 25 and average_watch < 20:
            return (
                f"{publication['platform']} {window}: average watch time is below 20 seconds; "
                "tighten the hook and move proof earlier."
            )
        if views or clicks or impressions:
            return (
                f"{publication['platform']} {window}: retain this package as a measured baseline and "
                "change only one creative variable in the next experiment."
            )
        return ""

    def dashboard(self) -> dict[str, Any]:
        publications = self.store.list_distribution_publications(limit=1000)
        counts: dict[str, int] = {}
        for item in publications:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {
            "publications": len(publications),
            "by_status": counts,
            "awaiting_founder": counts.get("awaiting_approval", 0),
            "reconciliation_required": counts.get("reconciliation_required", 0),
            "published": counts.get("published", 0),
        }


__all__ = [
    "DistributionEngine",
    "PUBLICATION_VISIBILITIES",
    "SUPPORTED_PLATFORMS",
    "TERMINAL_PUBLICATION_STATES",
]
