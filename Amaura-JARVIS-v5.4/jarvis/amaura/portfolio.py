"""Deterministic cross-mission portfolio arbitration for Amaura v7.

The arbitrator changes *attention*, not authority.  It ranks already-runnable
internal missions using founder priority, unresolved company signals, retry
health and starvation age.  It cannot approve, execute, spend, publish or
create external side effects.
"""

from __future__ import annotations

import datetime
from typing import Any

from jarvis.amaura.control_plane import AmauraControlPlane


_DOMAIN_SIGNALS: dict[str, set[str]] = {
    "software": {"build_failure", "release_ready", "security_incident"},
    "company": {"security_incident", "runway_risk", "customer_feedback", "revenue_signal"},
    "operations": {"security_incident", "runway_risk", "customer_feedback", "revenue_signal"},
    "revenue": {"revenue_signal", "customer_feedback", "runway_risk"},
    "ventures": {"venture_opportunity", "revenue_signal", "runway_risk"},
    "content": {"content_underperformance", "customer_feedback"},
    "research": {"research_opportunity"},
    "direct_action": set(),
}

_SEVERITY_BOOST = {"critical": 120.0, "high": 70.0, "medium": 35.0, "low": 10.0}


def _parse_time(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)
    except (TypeError, ValueError):
        return None


class PortfolioArbitrator:
    """Rank runnable founder missions using current company pressure."""

    def __init__(self, control: AmauraControlPlane) -> None:
        self.control = control

    def _signals(self) -> list[dict[str, Any]]:
        # Claimed signals are already being handled by another bounded workflow;
        # only unresolved pending pressure should influence new scheduling.
        return self.control.store.list_company_signals(status="pending", limit=500)

    @staticmethod
    def _domain(goal: dict[str, Any]) -> str:
        metadata = dict(goal.get("metadata") or {})
        plan = dict(metadata.get("goal_plan") or {})
        return str(plan.get("domain") or metadata.get("domain") or "operations").strip().lower()

    def score_goal(self, goal: dict[str, Any], *, now: datetime.datetime | None = None) -> dict[str, Any]:
        now = now or datetime.datetime.now(datetime.UTC)
        metadata = dict(goal.get("metadata") or {})
        priority = max(1, min(int(goal.get("priority") or 3), 5))
        domain = self._domain(goal)
        score = float((6 - priority) * 100)
        reasons = [f"founder_priority={priority}"]

        matching_types = _DOMAIN_SIGNALS.get(domain, set())
        signal_boost = 0.0
        matched: list[str] = []
        for signal in self._signals():
            signal_type = str(signal.get("signal_type") or "")
            if signal_type not in matching_types:
                continue
            severity = str(signal.get("severity") or "low").lower()
            boost = _SEVERITY_BOOST.get(severity, 0.0)
            signal_boost += boost
            matched.append(f"{signal_type}:{severity}")
        # Multiple correlated signals matter, but an unbounded signal backlog
        # must not starve every other mission forever.
        signal_boost = min(signal_boost, 180.0)
        if signal_boost:
            score += signal_boost
            reasons.append(f"signal_pressure=+{signal_boost:.0f}")

        last_advanced = _parse_time(metadata.get("runner_last_advanced_at"))
        if last_advanced is None:
            starvation_boost = 25.0
        else:
            age_minutes = max(0.0, (now - last_advanced).total_seconds() / 60.0)
            starvation_boost = min(40.0, age_minutes / 15.0 * 5.0)
        score += starvation_boost
        if starvation_boost:
            reasons.append(f"fairness=+{starvation_boost:.1f}")

        failures = max(0, int(metadata.get("runner_failure_count", 0) or 0))
        if failures:
            retry_penalty = min(80.0, float(failures * 20))
            score -= retry_penalty
            reasons.append(f"retry_health=-{retry_penalty:.0f}")

        return {
            "goal_id": str(goal.get("id") or ""),
            "domain": domain,
            "score": round(score, 3),
            "matched_signals": matched[:20],
            "reasons": reasons,
        }

    def rank_goals(self, goals: list[dict[str, Any]], *, now: datetime.datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.datetime.now(datetime.UTC)
        scored = [(self.score_goal(goal, now=now), goal) for goal in goals]
        scored.sort(
            key=lambda pair: (
                -float(pair[0]["score"]),
                str(pair[1].get("created_at") or ""),
                str(pair[1].get("id") or ""),
            )
        )
        return [goal for _score, goal in scored]

    def snapshot(self, goals: list[dict[str, Any]], *, now: datetime.datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.datetime.now(datetime.UTC)
        rows = [self.score_goal(goal, now=now) for goal in goals]
        return sorted(rows, key=lambda row: (-float(row["score"]), row["goal_id"]))


__all__ = ["PortfolioArbitrator"]