from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from jarvis.amaura.company_autonomy import CompanyAutonomyEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.ventures import VentureStudio
from jarvis.amaura.workflows import WORKFLOWS


def _fake_public_fetch(url: str, *, max_length: int = 200_000):
    payload = (
        "Students report repeated errors. Existing tools lack mistake-first revision. "
        "The problem is frequent and users actively seek a focused solution."
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
    monkeypatch.setenv("AMAURA_EVIDENCE_HMAC_KEY", "e" * 64)
    monkeypatch.setattr("jarvis.amaura.ventures.fetch_public_bytes", _fake_public_fetch)
    control = AmauraControlPlane(db_path=root / "amaura.db")
    control.store.set_control("company_repository_path", str(root), control.founder_id)
    return control


def _qualified(studio: VentureStudio):
    return studio.create_opportunity(
        title="NEET mistake tracker",
        problem="Students repeat the same mistakes because revision evidence is fragmented",
        target_user="NEET repeaters using NCERT and test series",
        product_type="mobile_app",
        source="public student interviews and forum threads",
        evidence=[
            {"source": "https://evidence-one.example/thread", "claim": "Students report repeated errors", "excerpt": "Students report repeated errors"},
            {"source": "https://evidence-two.example/reviews", "claim": "Existing tools lack mistake-first revision", "excerpt": "Existing tools lack mistake-first revision"},
        ],
        score_components={
            "pain": 90,
            "evidence": 85,
            "distribution_fit": 80,
            "speed": 90,
            "monetization": 70,
            "strategic_fit": 85,
        },
        estimated_build_days=10,
        monetization="Free core with a low-cost premium review plan",
        distribution_channel="NEET YouTube and student communities",
        strategic_fit="Founder understands the user and the product can fund AI research",
    )


def test_venture_catalogue_and_score_are_deterministic(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            studio = VentureStudio(control)
            opportunity = _qualified(studio)
            assert opportunity["total_score"] == 78
            assert opportunity["status"] == "review_required"
            assert opportunity["estimated_build_days"] <= 14
            assert {"venture_opportunity_cycle", "venture_validation_sprint", "venture_cashflow_cycle", "venture_portfolio_review"}.issubset(WORKFLOWS)
            assert control.dashboard()["ventures"]["qualified_opportunities"] == 0
        finally:
            control.close()


def test_venture_rejects_weak_or_unbounded_ideas(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            studio = VentureStudio(control)
            with pytest.raises(GovernanceError):
                studio.create_opportunity(
                    title="Everything app",
                    problem="Vague",
                    target_user="Everyone",
                    product_type="micro_saas",
                    source="guess",
                    evidence=[],
                    score_components={key: 100 for key in ("pain", "evidence", "distribution_fit", "speed", "monetization", "strategic_fit")},
                    estimated_build_days=30,
                    monetization="Unknown",
                    distribution_channel="Everywhere",
                    strategic_fit="",
                )
        finally:
            control.close()


def test_founder_starts_one_timeboxed_validation_sprint(monkeypatch):
    with TemporaryDirectory() as temp:
        root = Path(temp)
        control = _control(monkeypatch, root)
        try:
            studio = VentureStudio(control)
            opportunity = _qualified(studio)
            result = studio.start_validation(
                opportunity_id=opportunity["id"],
                product_name="NEET Error Loop",
                hypothesis="A mistake-first revision loop produces 25 qualified weekly users",
                primary_metric="qualified_weekly_users",
                target_value=25,
                kill_threshold=5,
                timebox_days=14,
                budget_cents=0,
            )
            experiment = result["experiment"]
            assert experiment["stage"] == "validating"
            assert experiment["timebox_days"] == 14
            assert result["programme"]["programme"]["workflow_id"] == "venture_validation_sprint"
            with pytest.raises(GovernanceError):
                studio.start_validation(
                    opportunity_id=opportunity["id"],
                    product_name="Second distraction",
                    hypothesis="Another test",
                    primary_metric="users",
                    target_value=10,
                    kill_threshold=1,
                )
        finally:
            control.close()


def test_venture_metric_requires_evidence_and_drives_recommendation(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            studio = VentureStudio(control)
            opportunity = _qualified(studio)
            experiment = studio.start_validation(
                opportunity_id=opportunity["id"],
                product_name="NEET Error Loop",
                hypothesis="Students will activate the mistake loop",
                primary_metric="qualified_weekly_users",
                target_value=25,
                kill_threshold=5,
            )["experiment"]
            with pytest.raises(GovernanceError):
                studio.record_metric(
                    experiment["id"], metric_name="qualified_weekly_users", value=25,
                    source="analytics", evidence=[]
                )
            recorded = studio.record_metric(
                experiment["id"],
                metric_name="qualified_weekly_users",
                value=27,
                source="product_analytics",
                evidence=[{"source": "analytics://venture", "claim": "27 activated users"}],
            )
            assert recorded["recommendation"]["recommendation"] == "double_down"
            decided = studio.decide(
                experiment["id"], decision="double_down", reason="Target exceeded with sourced activation data"
            )
            assert decided["stage"] == "scaling"
        finally:
            control.close()


def test_expired_weak_sprint_recommends_kill(monkeypatch):
    with TemporaryDirectory() as temp:
        control = _control(monkeypatch, Path(temp))
        try:
            studio = VentureStudio(control)
            opportunity = _qualified(studio)
            experiment = studio.start_validation(
                opportunity_id=opportunity["id"],
                product_name="NEET Error Loop",
                hypothesis="Students will activate the mistake loop",
                primary_metric="qualified_weekly_users",
                target_value=25,
                kill_threshold=5,
                timebox_days=7,
            )["experiment"]
            after_deadline = datetime.fromisoformat(experiment["deadline"]) + timedelta(seconds=1)
            recommendation = studio.recommend(experiment["id"], now=after_deadline)
            assert recommendation["recommendation"] == "kill"
        finally:
            control.close()


def test_company_bootstrap_includes_separate_ventures_objectives(monkeypatch):
    with TemporaryDirectory() as temp:
        root = Path(temp)
        control = _control(monkeypatch, root)
        try:
            company = CompanyAutonomyEngine(control)
            result = company.bootstrap_company(repository_path=str(root))
            titles = {item["title"] for item in result["portfolio"]["objectives"]}
            assert "Amaura Ventures opportunity pipeline" in titles
            assert "Amaura Ventures portfolio discipline" in titles
        finally:
            control.close()
