"""Content-factory asset, licence, publication, and learning controls."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from jarvis.amaura.models import ContentCampaign, ContentAsset, GovernanceError
from jarvis.amaura.store import CompanyStore

REQUIRED_PUBLICATION_ASSETS = {"master", "claim_map", "licence_inventory", "qa_report", "metadata"}
MEASUREMENT_WINDOWS = {"24h", "72h", "7d", "30d"}

def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"

class ContentFactory:
    """Govern content artefacts independently from model-generated prose."""

    def __init__(self, store: CompanyStore, founder_id: str = "founder"):
        self.store = store
        self.founder_id = founder_id

    def create_campaign(self, *, campaign_id: str, title: str, audience: str,
                        business_objective: str, config: dict | None = None) -> dict:
        if not all(value.strip() for value in (campaign_id, title, audience, business_objective)):
            raise GovernanceError("Content campaign id, title, audience, and business objective are required")
        payload = {
            "id": campaign_id, "title": title.strip(), "audience": audience.strip(),
            "business_objective": business_objective.strip(), "config": config or {},
        }
        try:
            validated = ContentCampaign.model_validate(payload)
            campaign = self.store.create_content_campaign(validated.model_dump())
        except Exception as exc:
            raise GovernanceError(f"Invalid campaign schema: {exc}")
        self.store.publish_event("content.campaign.created", campaign_id, {
            "audience": audience, "business_objective": business_objective,
        })
        return campaign

    def register_asset(self, campaign_id: str, *, asset_type: str, uri: str,
                       content: bytes | None = None, sha256: str = "", source_url: str = "",
                       creator: str = "", licence: str = "", status: str = "draft",
                       metadata: dict | None = None) -> dict:
        self.store.get_content_campaign(campaign_id)
        if not asset_type.strip() or not uri.strip():
            raise GovernanceError("Asset type and URI are required")
        digest = sha256.lower().strip() or (hashlib.sha256(content).hexdigest() if content is not None else "")
        if not digest or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise GovernanceError("Every content asset requires a valid SHA-256 digest")
        parsed = urlsplit(uri)
        is_external = parsed.scheme in {"http", "https"}
        if is_external and (not source_url.startswith(("http://", "https://")) or not licence.strip()):
            raise GovernanceError("External assets require a source URL and recorded licence")
        if not is_external and parsed.scheme not in {"", "file", "artifact"}:
            raise GovernanceError("Unsupported asset URI scheme")
        if status not in {"draft", "approved", "rejected"}:
            raise GovernanceError("Invalid content asset status")
        payload = {
            "id": _id("asset"), "campaign_id": campaign_id, "asset_type": asset_type.strip(),
            "uri": uri.strip(), "sha256": digest, "source_url": source_url.strip(),
            "creator": creator.strip(), "licence": licence.strip(), "status": status,
            "asset_metadata": metadata or {},
        }
        try:
            validated = ContentAsset.model_validate(payload)
            payload_to_store = validated.model_dump()
        except Exception as exc:
            raise GovernanceError(f"Invalid asset schema: {exc}")
        try:
            return self.store.add_content_asset(payload_to_store)
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise GovernanceError("This exact campaign asset is already registered") from exc
            raise

    def publication_readiness(self, campaign_id: str) -> dict:
        assets = self.store.list_content_assets(campaign_id)
        approved_types = {asset["asset_type"] for asset in assets if asset["status"] == "approved"}
        missing = sorted(REQUIRED_PUBLICATION_ASSETS - approved_types)
        licence_issues = [
            asset["id"] for asset in assets
            if urlsplit(asset["uri"]).scheme in {"http", "https"}
            and (not asset["licence"] or not asset["source_url"])
        ]
        duplicate_hashes = len({asset["sha256"] for asset in assets}) != len(assets)
        ready = not missing and not licence_issues and not duplicate_hashes
        return {
            "campaign_id": campaign_id, "ready": ready, "missing_approved_asset_types": missing,
            "licence_issues": licence_issues, "duplicate_hashes": duplicate_hashes,
            "asset_count": len(assets), "founder_approval_required": True,
        }

    def record_metrics(self, campaign_id: str, *, platform: str, window: str,
                       metrics: dict[str, int | float], captured_at: str | None = None) -> dict:
        self.store.get_content_campaign(campaign_id)
        if window not in MEASUREMENT_WINDOWS:
            raise GovernanceError(f"Measurement window must be one of: {', '.join(sorted(MEASUREMENT_WINDOWS))}")
        if not platform.strip() or not metrics:
            raise GovernanceError("Platform and at least one metric are required")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 for value in metrics.values()):
            raise GovernanceError("Content metrics must be non-negative numbers")
        return self.store.record_content_metrics({
            "id": _id("metric"), "campaign_id": campaign_id, "platform": platform.strip().lower(),
            "window": window, "captured_at": captured_at or datetime.now(UTC).isoformat(), "metrics": metrics,
        })


__all__ = ["ContentFactory", "MEASUREMENT_WINDOWS", "REQUIRED_PUBLICATION_ASSETS"]
