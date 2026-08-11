from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jarvis import cli
from jarvis.network_security import is_loopback_host, validate_bind_security
from jarvis.server import app


def _ws_protocols(key: str) -> list[str]:
    encoded = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
    return ["jarvis", f"jarvis-key.{encoded}"]


def test_configured_host_is_passed_to_uvicorn(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_run(app_name: str, **kwargs):
        captured["app"] = app_name
        captured.update(kwargs)

    monkeypatch.setenv("JARVIS_API_KEY", "k" * 48)
    with patch("uvicorn.run", side_effect=fake_run):
        cli._run_web_server("127.0.0.1", 8765)
    assert captured["app"] == "jarvis.server:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
    assert os.environ["JARVIS_EFFECTIVE_BIND_HOST"] == "127.0.0.1"


def test_non_loopback_bind_fails_closed_without_strong_key():
    with pytest.raises(RuntimeError, match="Refusing non-loopback"):
        validate_bind_security("0.0.0.0", "")
    with pytest.raises(RuntimeError, match="Refusing non-loopback"):
        validate_bind_security("192.168.1.10", "short")
    validate_bind_security("0.0.0.0", "x" * 48)
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")


def test_general_api_requires_local_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    key = "local-" + "a" * 48
    monkeypatch.setenv("JARVIS_HOST", "127.0.0.1")
    monkeypatch.setenv("JARVIS_EFFECTIVE_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("JARVIS_REQUIRE_LOCAL_AUTH", "1")
    monkeypatch.setenv("JARVIS_API_KEY", key)
    with TestClient(app) as client:
        assert client.get("/api/system").status_code == 403
        assert client.get("/api/system", headers={"X-Jarvis-Key": key}).status_code == 200


def test_websocket_always_requires_key(monkeypatch: pytest.MonkeyPatch):
    key = "ws-" + "b" * 48
    monkeypatch.setenv("JARVIS_HOST", "127.0.0.1")
    monkeypatch.setenv("JARVIS_EFFECTIVE_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("JARVIS_API_KEY", key)
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/chat"):
                pass
        with client.websocket_connect("/ws/chat", subprotocols=_ws_protocols(key)) as websocket:
            welcome = websocket.receive_json()
            assert welcome["type"] == "system"


def test_legacy_web_exports_governed_server():
    from jarvis import web
    from jarvis import server

    assert web.app is server.app
    assert web.main is server.main


def test_external_process_calls_are_bounded():
    root = Path(__file__).parents[1]
    fleet = (root / "jarvis" / "fleet.py").read_text(encoding="utf-8")
    hud = (root / "jarvis" / "hud.py").read_text(encoding="utf-8")
    assert "timeout=LAUNCHCTL_TIMEOUT_SECONDS" in fleet
    assert "timeout=HUD_SUBPROCESS_TIMEOUT_SECONDS" in hud


def test_security_scanner_rejects_hard_coded_wildcard_bind(tmp_path: Path):
    from jarvis.amaura.doctor import scan_repository

    package = tmp_path / "jarvis"
    package.mkdir()
    (package / "unsafe.py").write_text('uvicorn.run("x:y", host="0.0.0.0")', encoding="utf-8")
    report = scan_repository(tmp_path)
    assert not report["ok"]
    assert {item["kind"] for item in report["findings"]} == {"hard_coded_wildcard_bind"}
