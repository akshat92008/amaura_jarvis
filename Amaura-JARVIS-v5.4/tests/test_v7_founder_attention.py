from types import SimpleNamespace

from jarvis.amaura.founder_attention import FounderAttentionEngine


class _World:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get(self, *, refresh=False):
        assert refresh is False
        return self.snapshot


def test_attention_interrupts_only_for_high_consequence_items():
    snapshot = {
        "pending_approvals": [
            {"id": "medium", "risk": "medium", "created_at": "2026-08-17T01:00:00Z"},
            {"id": "high", "risk": "high", "created_at": "2026-08-17T02:00:00Z"},
        ],
        "open_alerts": [{"id": "warn", "severity": "warning", "created_at": "2026-08-17T00:00:00Z"}],
    }
    engine = FounderAttentionEngine(SimpleNamespace(), world=_World(snapshot))

    result = engine.summary()

    assert result["interrupt_founder"] is True
    assert result["urgent_decision_count"] == 1
    assert result["pending_approvals"][0]["id"] == "high"
    assert result["authority"] == "founder_only"
    assert result["background_work_may_continue"] is True


def test_medium_approval_does_not_stop_safe_background_work():
    snapshot = {
        "pending_approvals": [{"id": "medium", "risk": "medium", "created_at": "2026-08-17T01:00:00Z"}],
        "open_alerts": [],
    }
    engine = FounderAttentionEngine(SimpleNamespace(), world=_World(snapshot))

    result = engine.summary()

    assert result["interrupt_founder"] is False
    assert result["decision_count"] == 1
    assert result["background_work_may_continue"] is True


def test_critical_operational_alert_interrupts_without_granting_authority():
    snapshot = {
        "pending_approvals": [],
        "open_alerts": [
            {"id": "critical", "severity": "critical", "created_at": "2026-08-17T00:00:00Z"},
        ],
    }
    engine = FounderAttentionEngine(SimpleNamespace(), world=_World(snapshot))

    result = engine.summary()

    assert result["interrupt_founder"] is True
    assert result["critical_alert_count"] == 1
    assert result["authority"] == "founder_only"
