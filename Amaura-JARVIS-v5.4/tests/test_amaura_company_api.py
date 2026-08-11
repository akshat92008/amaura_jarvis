from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.server import app


@pytest.fixture
def company_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", "operator-secret")
    monkeypatch.setenv("AMAURA_APPROVAL_KEY", "approval-secret")
    monkeypatch.setenv("AMAURA_DISABLE_CLOUD", "1")
    monkeypatch.setenv("AMAURA_EVIDENCE_HMAC_KEY", "e" * 64)
    def fake_fetch(url: str, *, max_length: int = 200_000):
        payload = b"Repeated errors are common. Students actively seek focused revision support."
        return payload, {"validated_hostname": url.split("/")[2], "validated_ip": "93.184.216.34", "status": 200, "headers": {"content-type": "text/plain"}}
    monkeypatch.setattr("jarvis.amaura.ventures.fetch_public_bytes", fake_fetch)
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    import jarvis.tools.amaura

    jarvis.tools.amaura._CONTROL = None
    yield TestClient(app), tmp_path
    control = jarvis.tools.amaura._CONTROL
    if control is not None:
        control.close()
    jarvis.tools.amaura._CONTROL = None
    os.chdir(old_cwd)


def test_company_api_bootstrap_signal_status_and_kill_switch(company_api):
    client, repository = company_api
    bootstrap = client.post(
        "/api/amaura/company/bootstrap",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={"repository_path": str(repository), "product_name": "Amaura Labs"},
    )
    assert bootstrap.status_code == 200, bootstrap.text
    assert len(bootstrap.json()["created"]) == 15

    signal = client.post(
        "/api/amaura/company/signals",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={
            "signal_type": "customer_feedback",
            "source": "support",
            "severity": "medium",
            "payload": {"product_name": "Nexus", "summary": "setup is confusing"},
        },
    )
    assert signal.status_code == 200, signal.text
    assert signal.json()["status"] == "pending"

    status = client.get(
        "/api/amaura/company/status",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
    )
    assert status.status_code == 200, status.text
    assert status.json()["bootstrapped"] is True
    assert status.json()["signals"]["pending"] == 1

    pause = client.post(
        "/api/amaura/company/autopilot",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={"enabled": False, "reason": "maintenance"},
    )
    assert pause.status_code == 200, pause.text
    assert pause.json()["enabled"] is False

    run = client.post(
        "/api/amaura/company/run-once",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={"max_work_units": 1, "max_new_programmes": 1, "max_signals": 1},
    )
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "paused"


def test_company_api_founder_surfaces_reject_operator_key(company_api):
    client, repository = company_api
    response = client.post(
        "/api/amaura/company/bootstrap",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={"repository_path": str(repository)},
    )
    assert response.status_code == 403


def test_ventures_api_enforces_operator_and_founder_boundaries(company_api):
    client, repository = company_api
    bootstrap = client.post(
        "/api/amaura/company/bootstrap",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={"repository_path": str(repository)},
    )
    assert bootstrap.status_code == 200

    opportunity = client.post(
        "/api/amaura/ventures/opportunities",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={
            "title": "NEET error tracker",
            "problem": "Students repeat mistakes because revision records are fragmented",
            "target_user": "NEET repeaters",
            "product_type": "mobile_app",
            "source": "public student research",
            "evidence": [
                {"source": "https://one.example/thread", "claim": "Repeated errors are common", "excerpt": "Repeated errors are common"},
                {"source": "https://two.example/reviews", "claim": "Students seek focused revision", "excerpt": "Students actively seek focused revision support"}
            ],
            "score_components": {
                "pain": 90,
                "evidence": 85,
                "distribution_fit": 80,
                "speed": 90,
                "monetization": 70,
                "strategic_fit": 85,
            },
            "estimated_build_days": 10,
            "monetization": "Low-cost premium plan",
            "distribution_channel": "NEET YouTube",
            "strategic_fit": "Founder-domain advantage",
        },
    )
    assert opportunity.status_code == 200, opportunity.text
    opportunity_id = opportunity.json()["id"]

    denied = client.post(
        "/api/amaura/ventures/founder/start",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={
            "opportunity_id": opportunity_id,
            "product_name": "NEET Error Loop",
            "hypothesis": "Students activate a mistake-first workflow",
            "primary_metric": "qualified_weekly_users",
            "target_value": 25,
            "kill_threshold": 5,
        },
    )
    assert denied.status_code == 403

    started = client.post(
        "/api/amaura/ventures/founder/start",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={
            "opportunity_id": opportunity_id,
            "product_name": "NEET Error Loop",
            "hypothesis": "Students activate a mistake-first workflow",
            "primary_metric": "qualified_weekly_users",
            "target_value": 25,
            "kill_threshold": 5,
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["experiment"]["timebox_days"] == 14


def test_cashflow_api_dashboard_tick_and_founder_stream(company_api):
    client, repository = company_api
    bootstrap = client.post(
        "/api/amaura/company/bootstrap",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={"repository_path": str(repository)},
    )
    assert bootstrap.status_code == 200
    opportunity = client.post(
        "/api/amaura/ventures/opportunities",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={
            "title": "Cashflow template pack",
            "problem": "Students need focused revision assets",
            "target_user": "NEET students",
            "product_type": "template_pack",
            "source": "public research",
            "evidence": [
                {"source": "https://one.example/thread", "claim": "Repeated errors are common", "excerpt": "Repeated errors are common"},
                {"source": "https://two.example/reviews", "claim": "Students seek focused revision", "excerpt": "Students actively seek focused revision support"},
            ],
            "score_components": {},
            "estimated_build_days": 4,
            "monetization": "One-time download",
            "distribution_channel": "Organic content",
            "strategic_fit": "Low founder attention",
        },
    )
    assert opportunity.status_code == 200, opportunity.text
    opp_id = opportunity.json()["id"]
    denied = client.post(
        "/api/amaura/ventures/cashflow/founder/streams",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={
            "opportunity_id": opp_id, "name": "Revision Pack", "lane": "template_pack",
            "platform": "owned storefront", "offer": "Original revision templates", "target_user": "NEET students",
            "distribution_channel": "organic content", "price_cents": 19900,
        },
    )
    assert denied.status_code == 403
    created = client.post(
        "/api/amaura/ventures/cashflow/founder/streams",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={
            "opportunity_id": opp_id, "name": "Revision Pack", "lane": "template_pack",
            "platform": "owned storefront", "offer": "Original revision templates", "target_user": "NEET students",
            "distribution_channel": "organic content", "price_cents": 19900,
        },
    )
    assert created.status_code == 200, created.text
    stream_id = created.json()["id"]
    tick = client.post("/api/amaura/ventures/cashflow/tick", headers={"X-Amaura-Operator-Key": "operator-secret"}, json={})
    assert tick.status_code == 200, tick.text
    assert tick.json()["proposals_created"]
    insecure = client.post(
        "/api/amaura/ventures/cashflow/financial-events",
        headers={"X-Amaura-Operator-Key": "operator-secret"},
        json={"stream_id": stream_id, "event_type": "revenue", "amount_cents": 19900, "source": "receipt", "evidence": [{"receipt": "sale-1"}]},
    )
    assert insecure.status_code == 400
    revenue = client.post(
        "/api/amaura/ventures/cashflow/founder/financial-events",
        headers={"X-Amaura-Approval-Key": "approval-secret"},
        json={
            "stream_id": stream_id,
            "event_type": "revenue",
            "amount_cents": 19900,
            "source": "founder_manual",
            "evidence": [{"founder_attestation": True, "manual_event_id": "manual-api-sale-1", "note": "Manual sale entry"}],
        },
    )
    assert revenue.status_code == 200, revenue.text
    assert revenue.json()["event"]["trust_level"] == "founder_manual"
    dashboard = client.get("/api/amaura/ventures/cashflow", headers={"X-Amaura-Operator-Key": "operator-secret"})
    assert dashboard.status_code == 200
    assert dashboard.json()["portfolio"]["totals_by_currency"]["INR"]["net_cashflow_cents"] == 19900
    runtime = client.get("/api/amaura/runtime/status", headers={"X-Amaura-Operator-Key": "operator-secret"})
    assert runtime.status_code == 200, runtime.text
    assert runtime.json()["company_autopilot_state"] in {"stopped", "starting", "online", "standby", "degraded"}
    assert "company_autopilot_last_error" in runtime.json()
