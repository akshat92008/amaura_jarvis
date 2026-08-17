from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jarvis.amaura.portfolio import PortfolioArbitrator


class _Store:
    def __init__(self, signals=None):
        self.signals = list(signals or [])

    def list_company_signals(self, *, status=None, limit=500):
        assert status == "pending"
        return self.signals[:limit]


def _goal(goal_id, domain, *, priority=3, last_advanced_at="", failures=0, created_at="2026-08-17T00:00:00+00:00"):
    return {
        "id": goal_id,
        "priority": priority,
        "created_at": created_at,
        "metadata": {
            "goal_plan": {"domain": domain},
            "runner_last_advanced_at": last_advanced_at,
            "runner_failure_count": failures,
        },
    }


def test_critical_company_pressure_can_outrank_static_priority():
    control = SimpleNamespace(
        store=_Store([{"signal_type": "runway_risk", "severity": "critical"}])
    )
    arbitrator = PortfolioArbitrator(control)
    now = datetime(2026, 8, 17, tzinfo=UTC)
    software = _goal("software", "software", priority=1, last_advanced_at=now.isoformat())
    revenue = _goal("revenue", "revenue", priority=2, last_advanced_at=now.isoformat())

    ranked = arbitrator.rank_goals([software, revenue], now=now)

    assert [item["id"] for item in ranked] == ["revenue", "software"]
    revenue_score = arbitrator.score_goal(revenue, now=now)
    assert "runway_risk:critical" in revenue_score["matched_signals"]


def test_fairness_prefers_starved_peer_at_equal_priority():
    control = SimpleNamespace(store=_Store())
    arbitrator = PortfolioArbitrator(control)
    now = datetime(2026, 8, 17, tzinfo=UTC)
    just_ran = _goal("recent", "software", priority=2, last_advanced_at=now.isoformat())
    starved = _goal(
        "starved",
        "software",
        priority=2,
        last_advanced_at=(now - timedelta(hours=2)).isoformat(),
    )

    ranked = arbitrator.rank_goals([just_ran, starved], now=now)

    assert [item["id"] for item in ranked] == ["starved", "recent"]


def test_retry_health_penalizes_poison_mission_without_cancelling_it():
    control = SimpleNamespace(store=_Store())
    arbitrator = PortfolioArbitrator(control)
    now = datetime(2026, 8, 17, tzinfo=UTC)
    healthy = _goal("healthy", "software", priority=2, last_advanced_at=now.isoformat())
    poison = _goal("poison", "software", priority=2, last_advanced_at=now.isoformat(), failures=3)

    ranked = arbitrator.rank_goals([poison, healthy], now=now)

    assert [item["id"] for item in ranked] == ["healthy", "poison"]
    poison_score = arbitrator.score_goal(poison, now=now)
    assert any(reason.startswith("retry_health=-") for reason in poison_score["reasons"])
