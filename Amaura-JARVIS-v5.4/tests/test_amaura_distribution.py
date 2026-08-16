from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.integrations import ApprovedPublicationAdapter, ProviderReceipt
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.supervisor import AmauraSupervisor

RECEIPT_KEY = "distribution-test-provider-receipt-key-with-32-bytes"


def _ready_campaign(control: AmauraControlPlane, campaign_id: str = "campaign1") -> list[dict]:
    factory = control.content_factory
    factory.create_campaign(
        campaign_id=campaign_id,
        title="Amaura Build Log",
        audience="AI builders",
        business_objective="Owned audience growth",
    )
    assets = []
    for index, asset_type in enumerate(("master", "claim_map", "licence_inventory", "qa_report", "metadata")):
        payload = f"{asset_type}-{index}".encode()
        assets.append(
            factory.register_asset(
                campaign_id,
                asset_type=asset_type,
                uri=f"artifact://{campaign_id}/{asset_type}.json",
                content=payload,
                status="approved",
                metadata={"verified": True},
            )
        )
    assert factory.publication_readiness(campaign_id)["ready"]
    return assets


@pytest.fixture()
def control():
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.dict("os.environ", {"AMAURA_PROVIDER_RECEIPT_KEY": RECEIPT_KEY}),
    ):
        instance = AmauraControlPlane(Path(directory) / "amaura.db")
        try:
            yield instance
        finally:
            instance.close()


def test_publication_is_hash_bound_and_founder_approved(control: AmauraControlPlane):
    assets = _ready_campaign(control)
    staged = control.distribution.stage_publication(
        campaign_id="campaign1",
        platform="youtube",
        title="Building Amaura Company OS",
        body="A verified build log with sources and limitations.",
        asset_ids=[asset["id"] for asset in assets],
        visibility="public",
        scheduled_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    publication = staged["publication"]
    assert publication["status"] == "awaiting_approval"
    assert staged["approval"]["status"] == "pending"

    with pytest.raises(GovernanceError, match="founder approval"):
        control.distribution.dispatch(publication["id"])

    control.decide_approval(
        staged["approval"]["id"],
        actor=control.founder_id,
        decision="approved",
        reason="Exact package, claims, licences, and timing checked.",
    )
    enqueued = control.distribution.dispatch(publication["id"])
    assert enqueued["status"] == "enqueued"
    event = control.store.get_outbox_event(enqueued["outbox_event_id"])
    assert event["operation"] == "publish_content"
    assert event["idempotency_key"] == publication["idempotency_key"]


def test_publication_confirmation_requires_exact_signed_receipt(control: AmauraControlPlane):
    assets = _ready_campaign(control)
    staged = control.distribution.stage_publication(
        campaign_id="campaign1",
        platform="linkedin",
        title="Amaura technical release",
        body="Release notes with verified proof.",
        asset_ids=[asset["id"] for asset in assets],
        visibility="public",
    )
    control.decide_approval(
        staged["approval"]["id"],
        actor=control.founder_id,
        decision="approved",
        reason="Approved exact release post.",
    )
    publication = control.distribution.dispatch(staged["publication"]["id"])
    payload = control.distribution._publication_payload(publication)
    receipt = ProviderReceipt.issue(
        provider="approved-publication",
        operation="publish_content",
        external_id="linkedin-post-123",
        idempotency_key=publication["idempotency_key"],
        payload=payload,
        status="published",
    )
    confirmed = control.distribution.confirm_publication(publication["id"], provider_receipt=receipt)
    assert confirmed["status"] == "published"
    assert confirmed["external_id"] == "linkedin-post-123"

    wrong = ProviderReceipt.issue(
        provider="approved-publication",
        operation="publish_content",
        external_id="bad-123",
        idempotency_key="wrong-key",
        payload=payload,
        status="published",
    )
    with pytest.raises(GovernanceError, match="idempotency key"):
        control.distribution.confirm_publication(publication["id"], provider_receipt=wrong)


def test_public_adapter_requires_provider_echoes():
    payload = {
        "publication_id": "pub1",
        "visibility": "public",
        "platform": "youtube",
        "title": "Release",
        "body": "Verified release",
        "assets": [],
    }

    def transport(_url, **kwargs):
        import hashlib
        import json

        digest = hashlib.sha256(
            json.dumps(
                kwargs["payload"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()
        return (
            201,
            {
                "id": "youtube-123",
                "provider": "approved-publication",
                "visibility": "published",
                "idempotency_key": "publication-key",
                "payload_sha256": digest,
            },
            {},
        )

    with (
        patch.dict(
            "os.environ",
            {
                "AMAURA_ENABLE_PUBLICATION": "1",
                "AMAURA_ENABLE_PUBLIC_PUBLISH": "1",
                "AMAURA_PROVIDER_RECEIPT_KEY": RECEIPT_KEY,
            },
        ),
        patch("jarvis.amaura.integrations.validate_public_url"),
    ):
        adapter = ApprovedPublicationAdapter(
            endpoint="https://api.example.com/publish",
            access_token="token",
            transport=transport,
        )
        receipt = adapter.publish(payload=payload, idempotency_key="publication-key")
        assert receipt.verify()
        assert receipt.external_id == "youtube-123"


def test_ambiguous_publish_is_quarantined(control: AmauraControlPlane):
    assets = _ready_campaign(control)
    staged = control.distribution.stage_publication(
        campaign_id="campaign1",
        platform="x",
        title="Amaura release",
        body="Verified release thread.",
        asset_ids=[asset["id"] for asset in assets],
        visibility="public",
    )
    control.decide_approval(
        staged["approval"]["id"],
        actor=control.founder_id,
        decision="approved",
        reason="Approved exact thread.",
    )
    publication = control.distribution.dispatch(staged["publication"]["id"])
    supervisor = AmauraSupervisor(control, automatic_reviews=False)
    with patch(
        "jarvis.amaura.supervisor.dispatch_outbox_event",
        side_effect=TimeoutError("provider response timed out after submission"),
    ):
        result = supervisor.tick()
    assert result["outbox_dispatched"][0]["status"] == "reconciliation_required"
    quarantined = control.store.get_distribution_publication(publication["id"])
    assert quarantined["status"] == "reconciliation_required"


def test_metrics_create_evidence_backed_learning(control: AmauraControlPlane):
    assets = _ready_campaign(control)
    staged = control.distribution.stage_publication(
        campaign_id="campaign1",
        platform="youtube",
        title="Amaura build log",
        body="Build log.",
        asset_ids=[asset["id"] for asset in assets],
        visibility="draft",
    )
    publication = staged["publication"]
    measured = control.distribution.record_metrics(
        publication["id"],
        window="24h",
        metrics={"impressions": 1000, "clicks": 8, "views": 50, "watch_time_seconds": 500},
    )
    assert "CTR is below 2%" in measured["lesson"]
    lessons = control.store.list_content_lessons("campaign1")
    assert len(lessons) == 1
    assert lessons[0]["evidence_refs"][0]["type"] == "content_metrics"


def test_autopilot_enqueues_approved_due_publication(control: AmauraControlPlane):
    from jarvis.amaura.autopilot import AutonomousCompanyRuntime

    assets = _ready_campaign(control)
    staged = control.distribution.stage_publication(
        campaign_id="campaign1",
        platform="github",
        title="Amaura release notes",
        body="Verified release evidence.",
        asset_ids=[asset["id"] for asset in assets],
        visibility="public",
        scheduled_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    control.decide_approval(
        staged["approval"]["id"],
        actor=control.founder_id,
        decision="approved",
        reason="Approved exact release package.",
    )
    runtime = AutonomousCompanyRuntime(control, automatic_reviews=False)
    with patch("jarvis.amaura.supervisor.dispatch_outbox_event", side_effect=GovernanceError("provider disabled")):
        result = runtime.tick(max_work_units=1, max_new_programmes=0)
    assert staged["publication"]["id"] in result["publications_enqueued"]


def test_concurrent_autopilots_enqueue_one_publication():
    with (
        tempfile.TemporaryDirectory() as directory,
        patch.dict("os.environ", {"AMAURA_PROVIDER_RECEIPT_KEY": RECEIPT_KEY}),
    ):
        db_path = Path(directory) / "amaura.db"
        first = AmauraControlPlane(db_path)
        second = AmauraControlPlane(db_path)
        try:
            assets = _ready_campaign(first)
            staged = first.distribution.stage_publication(
                campaign_id="campaign1",
                platform="youtube",
                title="Exactly once release",
                body="Verified release.",
                asset_ids=[asset["id"] for asset in assets],
                visibility="public",
                scheduled_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            )
            first.decide_approval(
                staged["approval"]["id"],
                actor=first.founder_id,
                decision="approved",
                reason="Approved exact package.",
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda control: control.distribution.dispatch_due(), (first, second)))
            assert sum(len(result) for result in results) == 1
            events = first.store.list_outbox_events(limit=100)
            matching = [event for event in events if event["operation"] == "publish_content"]
            assert len(matching) == 1
            enqueued_events = first.store.list_events("distribution.publication.enqueued", limit=100)
            assert (
                len([event for event in enqueued_events if event["aggregate_id"] == staged["publication"]["id"]]) == 1
            )
            audits = first.store.list_audit(limit=200)
            assert (
                len(
                    [
                        entry
                        for entry in audits
                        if entry["action"] == "enqueue_publication"
                        and entry["resource_id"] == staged["publication"]["id"]
                    ]
                )
                == 1
            )
            publication = first.store.get_distribution_publication(staged["publication"]["id"])
            assert publication["outbox_event_id"] == matching[0]["id"]
        finally:
            first.close()
            second.close()
