from __future__ import annotations

from types import SimpleNamespace

from jarvis.arch_telegram import ArchTelegramAgentProxy, telegram_configured


def test_arch_telegram_proxy_routes_through_executive_kernel(monkeypatch):
    calls = []

    class FakeAgent:
        working_dir = "/tmp/workspace"

        def run_executive(self, text, **kwargs):
            calls.append((text, kwargs))
            return {"message": "done"}

    monkeypatch.setattr("jarvis.tools.amaura.get_control_plane", lambda: SimpleNamespace())
    proxy = ArchTelegramAgentProxy(FakeAgent())

    assert proxy.run_non_interactive("Open Safari") == "done"
    assert calls[0][0] == "Open Safari"
    assert calls[0][1]["session_id"] == "arch-telegram"
    assert calls[0][1]["autonomy"] == "execute_until_approval"
    assert calls[0][1]["coding_backend"] == "antigravity"
    assert calls[0][1]["allow_missions"] is True
    assert calls[0][1]["allow_memory_mutation"] is True


def test_arch_telegram_only_autostarts_when_both_credentials_exist(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
    assert telegram_configured() is False

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    assert telegram_configured() is False

    monkeypatch.setenv("TELEGRAM_USER_ID", "123")
    assert telegram_configured() is True
