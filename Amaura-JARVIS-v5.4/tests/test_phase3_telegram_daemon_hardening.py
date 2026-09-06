import os
from pathlib import Path
import pytest
from jarvis.amaura.channels import TelegramNotificationAdapter
from jarvis.arch_macos_service import launch_agent_payload

def test_telegram_buttons_serialization():
    sent_payloads = []
    def fake_transport(url, method="POST", payload=None, headers=None, timeout=20):
        sent_payloads.append(payload)
        return 200, {"ok": True, "result": {"message_id": 99, "chat": {"id": "12345"}}}, {}

    adapter = TelegramNotificationAdapter(
        token="fake-token",
        chat_id="12345",
        transport=fake_transport,
        receipt_key="x" * 32,
    )
    buttons = [
        [{"text": "✅ Approve", "callback_data": "amaura:approved:app-1"}, {"text": "❌ Reject", "callback_data": "amaura:rejected:app-1"}]
    ]
    receipt = adapter.send(
        text="Action required",
        idempotency_key="key-1",
        buttons=buttons,
    )
    assert receipt.status == "sent"
    assert len(sent_payloads) == 1
    assert "reply_markup" in sent_payloads[0]
    assert sent_payloads[0]["reply_markup"] == {"inline_keyboard": buttons}

def test_launch_agent_caffeinate_wrapper(tmp_path):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.touch(mode=0o755)
    env_file = tmp_path / ".env.amaura"
    env_file.write_text("AMAURA_TEST=1", encoding="utf-8")
    env_file.chmod(0o600)

    payload = launch_agent_payload(tmp_path)
    args = payload["ProgramArguments"]
    if Path("/usr/bin/caffeinate").exists():
        assert args[0] == "/usr/bin/caffeinate"
        assert args[1] == "-s"
        assert "-m" in args
        assert "jarvis.arch" in args
