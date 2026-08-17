"""Exception-based founder attention management for Amaura v7.

The engine is deliberately read-only. It decides what deserves the founder's
attention; it never grants approval or mutates the approval boundary.
"""

from __future__ import annotations

from typing import Any

from jarvis.amaura.cognition import WorldModel
from jarvis.amaura.control_plane import AmauraControlPlane

_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "": 4}


class FounderAttentionEngine:
    """Reduce company state to the decisions that genuinely require the founder."""

    def __init__(self, control: AmauraControlPlane, *, world: WorldModel | None = None) -> None:
        self.control = control
        self.world = world or WorldModel(control)

    def summary(self, *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = snapshot or self.world.get(refresh=False)
        approvals = [dict(item) for item in snapshot.get("pending_approvals", [])]
        alerts = [dict(item) for item in snapshot.get("open_alerts", [])]

        approvals.sort(
            key=lambda item: (
                _RISK_ORDER.get(str(item.get("risk") or "").lower(), 4),
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            )
        )
        alerts.sort(
            key=lambda item: (
                _RISK_ORDER.get(str(item.get("severity") or "").lower(), 4),
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            )
        )

        urgent_approvals = [
            item for item in approvals if str(item.get("risk") or "").lower() in {"critical", "high"}
        ]
        urgent_alerts = [item for item in alerts if str(item.get("severity") or "").lower() == "critical"]
        interrupt = bool(urgent_approvals or urgent_alerts)

        return {
            "interrupt_founder": interrupt,
            "decision_count": len(approvals),
            "urgent_decision_count": len(urgent_approvals),
            "critical_alert_count": len(urgent_alerts),
            "pending_approvals": approvals[:25],
            "critical_alerts": urgent_alerts[:25],
            "background_work_may_continue": True,
            "authority": "founder_only",
        }


__all__ = ["FounderAttentionEngine"]
