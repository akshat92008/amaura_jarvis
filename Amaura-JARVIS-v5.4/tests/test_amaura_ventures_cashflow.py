from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.ventures import VentureStudio
from jarvis.amaura.ventures_cashflow import CashflowEngine, LANE_PROFILES


def _fake_public_fetch(url: str, *, max_length: int = 200_000):
    payload = (
        "Creators repeatedly ask for faster revision templates and practical exam trackers. "
        "Students pay for focused resources when the product saves time and avoids repeated mistakes."
    ).encode()
    return payload, {
        "validated_hostname": url.split("/")[2],
        "validated_ip": "93.184.216.34",
        "status": 200,
        "headers": {"content-type": "text/plain"},
    }


def _control(monkeypatch, root: Path) -> AmauraControlPlane:
    monkeypatch.setenv("AMAURA_DATA_DIR", str(root / "data"))
    monkeypatch.setenv("AMAURA_EVIDENCE_DIR", str(root / "evidence"))
    monkeypatch.setenv("AMAURA_EVIDENCE_HMAC_KEY", "f" * 64)
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", "p" * 64)
    monkeypatch.setattr("jarvis.amaura.ventures.fetch_public_bytes", _fake_public_fetch)
    control = AmauraControlPlane(db_path=root / "amaura.db")
    control.store.set_control("company_repository_path", str(root), control.founder_id)
    return control


def _opportunity(studio: VentureStudio, product_type: str = "digital_download"):
    return studio.create_opportunity(
        title=f"Revision product {product_type}",
        problem="Students lose time because mistake-oriented revision resources are fragmented",
        target_user="NEET students with repeated test mistakes",
        product_type=product_type,
        source="public student discussions",
        evidence=[
            {"source": "https://one.example/thread", "claim": "Creators repeatedly ask for faster revision templates", "excerpt": "Creators repeatedly ask for faster revision templates"},
            {"source": "https://two.example/reviews", "claim": "Students pay for focused resources", "excerpt": "Students pay for focused resources"},
        ],
        score_components={},
        estimated_build_days=4,
        monetization="One-time paid download",
        distribution_channel="Organic student content and owned landing page",
        strategic_fit="Low-capital owned product with bounded founder attention",
    )


def _provider_evidence(external_id: str, *, amount_cents: int, event_type: str = "revenue", units: int = 0) -> list[dict]:
    from jarvis.amaura.integrations import ProviderReceipt
    payload = {"amount_cents": amount_cents, "event_type": event_type, "currency": "INR"}
    if units:
        payload["units"] = units
    receipt = ProviderReceipt.issue(
        provider="test-store", operation=f"financial_{event_type}", external_id=external_id,
        idempotency_key=f"idem-{external_id}-{event_type}", payload=payload, status="confirmed",
    )
    return [{"provider_receipt": receipt.to_dict(), "provider_payload": payload}]


def test_cashflow_lane_catalogue_and_ranking(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            studio = VentureStudio(control)
            opp = _opportunity(studio)
            engine = CashflowEngine(control)
            ranking = engine.rank_opportunity(opp, founder_minutes_per_week=60)
            assert ranking["lane"] == "digital_download"
            assert ranking["cashflow_score"] >= 70
            assert "kdp_book" in LANE_PROFILES
            assert "template_pack" in LANE_PROFILES
            assert "affiliate_content" in LANE_PROFILES
        finally:
            control.close()


def test_stream_creation_is_founder_gated_and_time_bounded(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            with pytest.raises(GovernanceError):
                engine.create_stream(
                    opportunity_id=opp["id"], name="Fast Revision Pack", lane="digital_download",
                    platform="owned storefront", offer="Original mistake-tracker PDF and spreadsheet",
                    target_user=opp["target_user"], distribution_channel="organic student content",
                    price_cents=19900, founder_minutes_per_week=30, actor="jarvis",
                )
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Fast Revision Pack", lane="digital_download",
                platform="owned storefront", offer="Original mistake-tracker PDF and spreadsheet",
                target_user=opp["target_user"], distribution_channel="organic student content",
                price_cents=19900, founder_minutes_per_week=30,
            )
            assert stream["status"] == "validation"
            assert stream["founder_minutes_per_week"] == 30
            assert stream["automation_level"] == 80
        finally:
            control.close()


def test_cashflow_financial_ledger_and_portfolio(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Fast Revision Pack", lane="digital_download",
                platform="owned storefront", offer="Original revision pack", target_user=opp["target_user"],
                distribution_channel="organic", price_cents=19900,
            )
            engine.record_financial_event(stream["id"], event_type="revenue", amount_cents=39800, source="store receipt", evidence=_provider_evidence("sale-1", amount_cents=39800, event_type="revenue"))
            engine.record_financial_event(stream["id"], event_type="fee", amount_cents=2000, source="processor receipt", evidence=_provider_evidence("fee-1", amount_cents=2000, event_type="fee"))
            engine.record_financial_event(stream["id"], event_type="refund", amount_cents=19900, source="store receipt", evidence=_provider_evidence("refund-1", amount_cents=19900, event_type="refund"))
            econ = engine.stream_economics(stream["id"])
            assert econ["gross_revenue_cents"] == 39800
            assert econ["net_cashflow_cents"] == 17900
            portfolio = engine.portfolio()
            assert portfolio["totals_by_currency"]["INR"]["net_cashflow_cents"] == 17900
        finally:
            control.close()


def test_cashflow_action_queue_fails_closed_for_external_actions(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Fast Revision Pack", lane="digital_download",
                platform="owned storefront", offer="Original revision pack", target_user=opp["target_user"],
                distribution_channel="organic", price_cents=19900,
            )
            actions = engine.tick()["proposals_created"]
            external = next(item for item in actions if item["requires_founder_approval"])
            with pytest.raises(GovernanceError):
                engine.set_action_status(external["id"], status="running", reason="try to publish", actor="jarvis")
            approved = engine.set_action_status(external["id"], status="approved", reason="Founder reviewed exact payload", actor=control.founder_id)
            assert approved["status"] == "running"
            assert approved["mission_id"]
        finally:
            control.close()


def test_cashflow_rejects_spam_and_plagiarism(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control), "kdp_book")
            engine = CashflowEngine(control)
            with pytest.raises(GovernanceError):
                engine.create_stream(
                    opportunity_id=opp["id"], name="Copied book", lane="kdp_book", platform="KDP",
                    offer="Plagiarize competitor books and use fake reviews", target_user=opp["target_user"],
                    distribution_channel="spam DM", price_cents=29900,
                )
        finally:
            control.close()


def test_goal_compiler_routes_side_hustle_to_ventures():
    from jarvis.amaura.brain import GoalCompiler, GoalRequest
    compiler = GoalCompiler()
    request = GoalRequest(objective="Build a continuous side hustle cashflow pipeline for Amaura Ventures")
    assert compiler.classify(request) == "ventures"
    plan = compiler.compile(request, memory_context="")
    assert plan.domain == "ventures"
    assert any(task.owner_id == "venture_director" for task in plan.tasks)


def test_company_bootstrap_includes_cashflow_objective(monkeypatch):
    from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
    with TemporaryDirectory() as temp:
        root = Path(temp)
        control = _control(monkeypatch, root)
        try:
            result = CompanyAutonomyEngine(control).bootstrap_company(repository_path=str(root))
            titles = {item["title"] for item in result["portfolio"]["objectives"]}
            assert "Amaura Ventures cash-flow engine" in titles
        finally:
            control.close()


def test_financial_events_are_idempotent_and_currency_safe(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Pack", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic",
                price_cents=10000,
            )
            first = engine.record_financial_event(stream["id"], event_type="revenue", amount_cents=10000, source="store", evidence=_provider_evidence("same-sale", amount_cents=10000, event_type="revenue"))
            second = engine.record_financial_event(stream["id"], event_type="revenue", amount_cents=10000, source="store", evidence=_provider_evidence("same-sale", amount_cents=10000, event_type="revenue"))
            assert first["event"]["id"] == second["event"]["id"]
            assert engine.stream_economics(stream["id"])["gross_revenue_cents"] == 10000
            with pytest.raises(GovernanceError):
                engine.record_financial_event(stream["id"], event_type="revenue", amount_cents=10000, source="store", evidence=_provider_evidence("usd-sale", amount_cents=10000, event_type="revenue"), currency="USD")
        finally:
            control.close()


def test_founder_time_cap_is_portfolio_wide(monkeypatch):
    with TemporaryDirectory() as temp:
        root = Path(temp)
        control = _control(monkeypatch, root)
        monkeypatch.setenv("AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY", "60")
        try:
            studio = VentureStudio(control)
            first = _opportunity(studio, "digital_download")
            second = studio.create_opportunity(
                title="Second cashflow product", problem="Students need a second focused resource", target_user="NEET students preparing weekly tests",
                product_type="template_pack", source="public student discussions",
                evidence=[
                    {"source": "https://three.example/thread", "claim": "Creators repeatedly ask for faster revision templates", "excerpt": "Creators repeatedly ask for faster revision templates"},
                    {"source": "https://four.example/reviews", "claim": "Students pay for focused resources", "excerpt": "Students pay for focused resources"},
                ], score_components={}, estimated_build_days=3, monetization="One-time sale", distribution_channel="organic", strategic_fit="low capital",
            )
            engine = CashflowEngine(control)
            engine.create_stream(opportunity_id=first["id"], name="One", lane="digital_download", platform="store", offer="Original one", target_user=first["target_user"], distribution_channel="organic", price_cents=10000, founder_minutes_per_week=40)
            with pytest.raises(GovernanceError):
                engine.create_stream(opportunity_id=second["id"], name="Two", lane="template_pack", platform="store", offer="Original two", target_user=second["target_user"], distribution_channel="organic", price_cents=10000, founder_minutes_per_week=30)
        finally:
            control.close()



def test_arbitrary_receipt_string_cannot_create_revenue(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Trust test", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            with pytest.raises(GovernanceError):
                engine.record_financial_event(
                    stream["id"], event_type="revenue", amount_cents=10000,
                    source="made-up", evidence=[{"receipt": "sale-1"}], actor="jarvis",
                )
        finally:
            control.close()


def test_founder_manual_finance_is_separate_from_provider_verified(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Manual test", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            engine.record_financial_event(
                stream["id"], event_type="revenue", amount_cents=7000, source="Founder bank statement",
                evidence=[{"founder_attestation": True, "manual_event_id": "manual-1", "note": "Manual reconciliation"}], actor=control.founder_id,
            )
            econ = engine.stream_economics(stream["id"])
            assert econ["gross_revenue_cents"] == 7000
            assert econ["provider_verified_revenue_cents"] == 0
            assert econ["founder_certified_revenue_cents"] == 7000
        finally:
            control.close()


def test_cashflow_action_uses_canonical_company_approval(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Approval test", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            external = next(a for a in engine.tick(auto_execute=False)["proposals_created"] if a["requires_founder_approval"])
            action = control.store.get_venture_cashflow_action(external["id"])
            assert action["approval_id"]
            approval = control.store.get_approval(action["approval_id"])
            assert approval["status"] == "pending"
            approved = engine.set_action_status(action["id"], status="approved", reason="Exact payload approved", actor=control.founder_id)
            assert approved["status"] == "running"
            assert approved["mission_id"]
            assert control.store.get_approval(action["approval_id"])["status"] == "approved"
        finally:
            control.close()


def test_cashflow_action_payload_mutation_invalidates_approval(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Mutation test", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            external = next(a for a in engine.tick(auto_execute=False)["proposals_created"] if a["requires_founder_approval"])
            action = control.store.get_venture_cashflow_action(external["id"])
            control.store.update_venture_cashflow_action(action["id"], payload={**action["payload"], "offer": "mutated after request"})
            with pytest.raises(GovernanceError):
                engine.set_action_status(action["id"], status="approved", reason="approve", actor=control.founder_id)
        finally:
            control.close()


def test_internal_cashflow_action_materializes_jarvis_mission(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Mission test", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            tick = engine.tick(auto_execute=True)
            internal = next(a for a in tick["action_queue"] if not a["requires_founder_approval"] and a["mission_id"])
            assert internal["status"] == "running"
            goal = control.store.get_work_item(internal["mission_id"])
            assert (goal.get("metadata") or {}).get("dynamic_goal") is True
        finally:
            control.close()



def test_provider_receipt_cannot_be_replayed_with_different_amount(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Receipt binding", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            evidence = _provider_evidence("sale-bound", amount_cents=10000)
            with pytest.raises(GovernanceError):
                engine.record_financial_event(
                    stream["id"], event_type="revenue", amount_cents=12000, source="store", evidence=evidence,
                )
        finally:
            control.close()


def test_unit_economics_separate_cogs_marketing_tax_and_operating_cost(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Economics", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic",
                price_cents=10000, unit_cost_cents=2000,
            )
            for typ, amount, ext, units in [
                ("revenue", 20000, "rev", 2), ("cogs", 4000, "cogs", 0), ("fee", 1000, "fee", 0),
                ("marketing", 2000, "mkt", 0), ("tax", 500, "tax", 0), ("cost", 500, "ops", 0),
            ]:
                engine.record_financial_event(
                    stream["id"], event_type=typ, amount_cents=amount, source="provider",
                    evidence=_provider_evidence(ext, amount_cents=amount, event_type=typ, units=units),
                )
            econ = engine.stream_economics(stream["id"])
            assert econ["gross_profit_cents"] == 16000
            assert econ["contribution_profit_cents"] == 13000
            assert econ["net_cashflow_cents"] == 12000
            assert econ["units_sold"] == 2
            assert econ["customer_acquisition_cost_cents"] == 1000
            assert econ["gross_margin_pct"] == 80.0
            assert econ["contribution_margin_pct"] == 65.0
            assert econ["net_margin_pct"] == 60.0
        finally:
            control.close()


def test_lane_ranking_learns_from_real_stream_outcomes(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            studio = VentureStudio(control)
            first = _opportunity(studio, "digital_download")
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=first["id"], name="Learning sample", lane="digital_download", platform="store",
                offer="Original pack", target_user=first["target_user"], distribution_channel="organic", price_cents=10000,
            )
            engine.record_financial_event(
                stream["id"], event_type="revenue", amount_cents=30000, source="provider",
                evidence=_provider_evidence("learn-rev", amount_cents=30000, event_type="revenue", units=3),
            )
            second = studio.create_opportunity(
                title="Second learned product", problem="Students need a compact weekly error review system",
                target_user="NEET students", product_type="digital_download", source="public discussion",
                evidence=[
                    {"source":"https://one.example/a","claim":"Creators repeatedly ask for faster revision templates","excerpt":"Creators repeatedly ask for faster revision templates"},
                    {"source":"https://two.example/b","claim":"Students pay for focused resources","excerpt":"Students pay for focused resources"},
                ], score_components={}, estimated_build_days=4, monetization="download", distribution_channel="organic", strategic_fit="low capital",
            )
            ranked = next(row for row in engine.ranked_opportunities(limit=20) if row["opportunity_id"] == second["id"])
            assert ranked["learning"]["sample_count"] >= 1
            assert ranked["learning"]["weight"] > 0
            assert "prior_cashflow_score" in ranked
        finally:
            control.close()


def test_founder_attention_admission_is_atomic_across_connections(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    with TemporaryDirectory() as temp:
        root = Path(temp)
        monkeypatch.setenv("AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY", "60")
        first_control = _control(monkeypatch, root)
        second_control = AmauraControlPlane(db_path=root / "amaura.db")
        try:
            studio = VentureStudio(first_control)
            one = _opportunity(studio, "digital_download")
            two = studio.create_opportunity(
                title="Concurrent product", problem="Students need a compact revision helper", target_user="NEET students",
                product_type="template_pack", source="public discussion",
                evidence=[
                    {"source":"https://one.example/c","claim":"Creators repeatedly ask for faster revision templates","excerpt":"Creators repeatedly ask for faster revision templates"},
                    {"source":"https://two.example/d","claim":"Students pay for focused resources","excerpt":"Students pay for focused resources"},
                ], score_components={}, estimated_build_days=3, monetization="sale", distribution_channel="organic", strategic_fit="low capital",
            )
            barrier = threading.Barrier(2)
            def create(control, opp, name, lane):
                barrier.wait()
                try:
                    CashflowEngine(control).create_stream(
                        opportunity_id=opp["id"], name=name, lane=lane, platform="store", offer="Original product",
                        target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
                        founder_minutes_per_week=40,
                    )
                    return "created"
                except GovernanceError:
                    return "blocked"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda args: create(*args), [
                    (first_control, one, "One", "digital_download"),
                    (second_control, two, "Two", "template_pack"),
                ]))
            assert sorted(results) == ["blocked", "created"]
            live_attention = sum(
                int(row["founder_minutes_per_week"]) for row in first_control.store.list_venture_cashflow_streams(limit=10)
                if row["status"] in {"validation", "ready", "live"}
            )
            assert live_attention == 40
        finally:
            second_control.close()
            first_control.close()


def test_live_stream_cap_transition_is_atomic(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    with TemporaryDirectory() as temp:
        root = Path(temp)
        monkeypatch.setenv("AMAURA_VENTURE_MAX_LIVE_STREAMS", "1")
        monkeypatch.setenv("AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY", "180")
        c1 = _control(monkeypatch, root)
        c2 = AmauraControlPlane(db_path=root / "amaura.db")
        try:
            studio = VentureStudio(c1)
            o1 = _opportunity(studio, "digital_download")
            o2 = studio.create_opportunity(
                title="Live cap second", problem="Students need another focused helper", target_user="NEET students",
                product_type="template_pack", source="public discussion",
                evidence=[
                    {"source":"https://one.example/e","claim":"Creators repeatedly ask for faster revision templates","excerpt":"Creators repeatedly ask for faster revision templates"},
                    {"source":"https://two.example/f","claim":"Students pay for focused resources","excerpt":"Students pay for focused resources"},
                ], score_components={}, estimated_build_days=3, monetization="sale", distribution_channel="organic", strategic_fit="low capital",
            )
            e1, e2 = CashflowEngine(c1), CashflowEngine(c2)
            s1 = e1.create_stream(opportunity_id=o1["id"], name="S1", lane="digital_download", platform="store", offer="Original", target_user=o1["target_user"], distribution_channel="organic", price_cents=10000, founder_minutes_per_week=20)
            s2 = e2.create_stream(opportunity_id=o2["id"], name="S2", lane="template_pack", platform="store", offer="Original", target_user=o2["target_user"], distribution_channel="organic", price_cents=10000, founder_minutes_per_week=20)
            e1.set_stream_status(s1["id"], status="ready", reason="validated")
            e2.set_stream_status(s2["id"], status="ready", reason="validated")
            barrier = threading.Barrier(2)
            def go(engine, sid):
                barrier.wait()
                try:
                    engine.set_stream_status(sid, status="live", reason="launch")
                    return "live"
                except GovernanceError:
                    return "blocked"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda args: go(*args), [(e1, s1["id"]), (e2, s2["id"])]))
            assert sorted(results) == ["blocked", "live"]
            assert len(c1.store.list_venture_cashflow_streams(status="live", limit=10)) == 1
        finally:
            c2.close(); c1.close()


def test_runtime_status_api_is_exposed():
    from jarvis.server import app
    assert "/api/amaura/runtime/status" in {getattr(route, "path", "") for route in app.routes}


def test_generic_company_approval_unblocks_venture_action_on_next_tick(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Generic approval", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            external = next(a for a in engine.tick(auto_execute=False)["proposals_created"] if a["requires_founder_approval"])
            action = control.store.get_venture_cashflow_action(external["id"])
            control.decide_approval(action["approval_id"], control.founder_id, "approved", "Approved in central approvals UI")
            assert control.store.get_venture_cashflow_action(action["id"])["status"] == "proposed"
            engine.tick(auto_execute=True)
            synced = control.store.get_venture_cashflow_action(action["id"])
            assert synced["status"] == "running"
            assert synced["mission_id"]
        finally:
            control.close()


def test_cancelling_cashflow_action_cancels_linked_jarvis_mission(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Cancel mission", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            engine.tick(auto_execute=True)
            action = next(a for a in engine.next_actions(limit=20) if not a["requires_founder_approval"] and a["mission_id"])
            cancelled = engine.set_action_status(action["id"], status="cancelled", reason="Founder stopped this experiment", actor=control.founder_id)
            assert cancelled["status"] == "cancelled"
            from jarvis.amaura.brain import JarvisBrain
            assert JarvisBrain(control).status(action["mission_id"])["state"] == "cancelled"
        finally:
            control.close()


def test_completed_jarvis_mission_closes_cashflow_action_with_evidence(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Completion sync", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            engine.tick(auto_execute=True)
            action = next(a for a in engine.next_actions(limit=20) if not a["requires_founder_approval"] and a["mission_id"])
            from jarvis.amaura.brain import JarvisBrain
            brain = JarvisBrain(control)
            status = brain.status(action["mission_id"])
            for task in status["tasks"]:
                control.store.update_work_item(
                    task["id"], state="completed", summary=f"Completed {task['title']}",
                    evidence=[{"type":"test", "success":True, "excerpt":"verified"}],
                )
            changed = engine.sync_action_missions()
            closed = control.store.get_venture_cashflow_action(action["id"])
            assert closed["status"] == "completed"
            assert closed["result"]["mission_results"]
            assert any(row["id"] == action["id"] for row in changed)
        finally:
            control.close()


def test_evidence_vault_provider_label_cannot_mint_verified_revenue(monkeypatch):
    """A signed Amaura evidence manifest is not proof that an external provider paid us."""
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Vault trust test", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            fake = control.evidence.put_json(
                {"amount_cents": 10000, "event_type": "revenue", "currency": "INR"},
                source="provider:made-up-store",
                retrieval_metadata={
                    "financial_trust": "provider_verified", "provider": "made-up-store",
                    "external_event_id": "fake-1", "amount_cents": 10000,
                    "event_type": "revenue", "currency": "INR",
                },
            )
            with pytest.raises(GovernanceError):
                engine.record_financial_event(
                    stream["id"], event_type="revenue", amount_cents=10000, source="vault",
                    evidence=[{"reference": fake.reference}], actor="jarvis",
                )
        finally:
            control.close()


def test_failed_cashflow_action_retry_creates_fresh_mission(monkeypatch):
    from jarvis.amaura.brain import JarvisBrain
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            engine.create_stream(
                opportunity_id=opp["id"], name="Retry mission", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            first = next(a for a in engine.tick(auto_execute=True)["action_queue"] if not a["requires_founder_approval"] and a["mission_id"])
            old_mission = first["mission_id"]
            JarvisBrain(control).cancel(old_mission, actor=control.founder_id, reason="simulate failed execution")
            engine.sync_action_missions()
            failed = control.store.get_venture_cashflow_action(first["id"])
            assert failed["status"] == "failed"
            reset = engine.set_action_status(failed["id"], status="proposed", reason="retry with fresh mission", actor="jarvis")
            assert reset["mission_id"] == ""
            assert reset["result"]["mission_history"][-1]["mission_id"] == old_mission
            engine.tick(auto_execute=True)
            retried = control.store.get_venture_cashflow_action(first["id"])
            assert retried["status"] == "running"
            assert retried["mission_id"] and retried["mission_id"] != old_mission
        finally:
            control.close()


def test_founder_manual_event_id_prevents_conflicting_duplicate(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Manual duplicate", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            evidence = [{"founder_attestation": True, "manual_event_id": "bank-txn-1", "note": "statement row"}]
            first = engine.record_financial_event(
                stream["id"], event_type="revenue", amount_cents=10000, source="bank", evidence=evidence,
                actor=control.founder_id,
            )
            second = engine.record_financial_event(
                stream["id"], event_type="revenue", amount_cents=10000, source="bank changed note",
                evidence=[{"founder_attestation": True, "manual_event_id": "bank-txn-1", "note": "same statement row, annotated"}],
                actor=control.founder_id,
            )
            assert first["event"]["id"] == second["event"]["id"]
            with pytest.raises(GovernanceError):
                engine.record_financial_event(
                    stream["id"], event_type="revenue", amount_cents=12000, source="bank", evidence=evidence,
                    actor=control.founder_id,
                )
        finally:
            control.close()


def test_failed_provider_receipt_cannot_count_as_financial_truth(monkeypatch):
    from jarvis.amaura.integrations import ProviderReceipt
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            opp = _opportunity(VentureStudio(control))
            engine = CashflowEngine(control)
            stream = engine.create_stream(
                opportunity_id=opp["id"], name="Failed receipt", lane="digital_download", platform="store",
                offer="Original pack", target_user=opp["target_user"], distribution_channel="organic", price_cents=10000,
            )
            payload = {"amount_cents": 10000, "event_type": "revenue", "currency": "INR"}
            receipt = ProviderReceipt.issue(
                provider="test-store", operation="financial_revenue", external_id="declined-1",
                idempotency_key="declined-idem", payload=payload, status="failed",
            )
            with pytest.raises(GovernanceError):
                engine.record_financial_event(
                    stream["id"], event_type="revenue", amount_cents=10000, source="store",
                    evidence=[{"provider_receipt": receipt.to_dict(), "provider_payload": payload}],
                )
        finally:
            control.close()


def test_v53_database_migrates_financial_and_action_trust_columns(monkeypatch):
    from jarvis.amaura.store import CompanyStore
    with TemporaryDirectory() as temp:
        root = Path(temp)
        db = root / "amaura-v53.db"
        connection = sqlite3.connect(db)
        connection.executescript(
            """
            CREATE TABLE venture_cashflow_streams (
                id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL DEFAULT '', experiment_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL, lane TEXT NOT NULL, platform TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
                offer TEXT NOT NULL DEFAULT '', target_user TEXT NOT NULL DEFAULT '', distribution_channel TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT 'INR', price_cents INTEGER NOT NULL DEFAULT 0, unit_cost_cents INTEGER NOT NULL DEFAULT 0,
                founder_minutes_per_week INTEGER NOT NULL DEFAULT 0, automation_level INTEGER NOT NULL DEFAULT 0, launch_url TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE venture_financial_events (
                id TEXT PRIMARY KEY, stream_id TEXT NOT NULL, event_type TEXT NOT NULL, amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL, source TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '[]', idempotency_key TEXT NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE venture_cashflow_actions (
                id TEXT PRIMARY KEY, stream_id TEXT NOT NULL DEFAULT '', action_type TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed', priority INTEGER NOT NULL DEFAULT 3, requires_founder_approval INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT '{}', due_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        connection.commit(); connection.close()
        monkeypatch.setenv("AMAURA_EVIDENCE_HMAC_KEY", "e" * 64)
        store = CompanyStore(db_path=db)
        try:
            finance_cols = {row[1] for row in store._connection.execute("PRAGMA table_info(venture_financial_events)").fetchall()}
            action_cols = {row[1] for row in store._connection.execute("PRAGMA table_info(venture_cashflow_actions)").fetchall()}
            assert {"trust_level", "provider", "external_event_id"} <= finance_cols
            assert {"payload_hash", "approval_id", "approval_task_id", "mission_id"} <= action_cols
        finally:
            store.close()
