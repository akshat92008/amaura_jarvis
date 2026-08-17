from __future__ import annotations

from datetime import UTC, datetime

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.inbox import InboundMessage
from jarvis.amaura.signal_ingestion import SignalIngestionEngine


class _FakeGmail:
    configured = True

    def __init__(self, messages):
        self.messages = list(messages)
        self.mark_read_calls = []

    def list_messages(self, *, query="is:unread", max_results=25):
        assert query == "is:unread"
        return self.messages[:max_results]

    def mark_read(self, external_id):  # pragma: no cover - this must never be called
        self.mark_read_calls.append(external_id)
        raise AssertionError("v7 signal ingestion must not acknowledge external mail")


def _message(*, external_id="m-1", body="Interested, please send more details"):
    return InboundMessage(
        provider="gmail",
        external_id=external_id,
        thread_id="thread-1",
        sender="prospect@example.com",
        recipient="founder@example.com",
        subject="Re: Amaura",
        body=body,
        received_at=datetime(2026, 8, 17, tzinfo=UTC).isoformat(),
        raw_metadata={"history_id": "42"},
    )


def test_gmail_observation_creates_company_signal_without_external_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_V7_EXTERNAL_SIGNAL_INGESTION", "1")
    control = AmauraControlPlane(tmp_path / "signal.db")
    fake = _FakeGmail([_message()])
    try:
        engine = SignalIngestionEngine(control, gmail_factory=lambda: fake)
        result = engine.poll_gmail()

        assert result["status"] == "ok"
        assert result["messages"] == 1
        assert fake.mark_read_calls == []
        signals = control.store.list_company_signals(status="pending", limit=20)
        assert len(signals) == 1
        assert signals[0]["signal_type"] == "revenue_signal"
        assert signals[0]["source"] == "inbox:gmail"
        assert "body" not in signals[0]["payload"]
        assert signals[0]["payload"]["classification"]["label"] == "interested"
    finally:
        control.close()


def test_inbound_signal_bridge_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_V7_EXTERNAL_SIGNAL_INGESTION", "1")
    control = AmauraControlPlane(tmp_path / "signal-idempotent.db")
    fake = _FakeGmail([_message(external_id="same-message")])
    try:
        engine = SignalIngestionEngine(control, gmail_factory=lambda: fake)
        first = engine.poll_gmail()
        second = engine.poll_gmail()

        assert first["status"] == "ok"
        assert second["status"] == "ok"
        signals = control.store.list_company_signals(limit=20)
        ids = {signal["id"] for signal in signals}
        assert len(ids) == 1
    finally:
        control.close()


def test_unconfigured_gmail_is_a_nonfatal_noop(tmp_path):
    control = AmauraControlPlane(tmp_path / "signal-unconfigured.db")

    class _Unconfigured:
        configured = False

    try:
        engine = SignalIngestionEngine(control, gmail_factory=_Unconfigured)
        result = engine.poll()
        assert result["status"] == "ok"
        assert result["gmail"]["status"] == "not_configured"
        assert result["signal_count"] == 0
    finally:
        control.close()
