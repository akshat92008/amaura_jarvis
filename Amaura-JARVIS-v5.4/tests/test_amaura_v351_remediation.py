from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jarvis.amaura.doctor import scan_repository
from jarvis.amaura.store import CompanyStore
from jarvis.server import app
from jarvis.tools.coding import tool_read_file, tool_web_fetch
from jarvis.tools.result import parse_tool_result
from jarvis.tools.security import tool_workspace


@pytest.mark.parametrize(
    "operation",
    ["send_email", "send_imessage", "sync_crm", "create_private_draft", "publish_content", "future_unknown_operation"],
)
def test_expired_external_operation_fails_closed_to_reconciliation(tmp_path: Path, operation: str):
    store = CompanyStore(tmp_path / "company.db")
    try:
        event = store.enqueue_outbox_event("provider", operation, {"x": 1}, f"key-{operation}")
        claimed = store.claim_outbox_events(worker_id="worker", lease_seconds=30)
        assert claimed and claimed[0]["id"] == event["id"]
        expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        store._connection.execute("UPDATE outbox_events SET lease_until=? WHERE id=?", (expired, event["id"]))
        store._connection.commit()
        recovered = store.recover_expired_outbox_events()
        assert recovered[0]["status"] == "reconciliation_required"
        assert recovered[0]["next_attempt_at"] is None
    finally:
        store.close()


def test_legacy_read_boundary_blocks_escape_and_secrets(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.txt").write_text("safe", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=1", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with tool_workspace(workspace):
        assert "safe" in tool_read_file("safe.txt")
        assert "Sensitive path is blocked" in tool_read_file(".env")
        assert "Path escapes approved workspace" in tool_read_file(str(outside))


def test_legacy_web_fetch_uses_governed_ssrf_boundary():
    result = tool_web_fetch("file:///etc/hosts")
    assert result.startswith("❌")
    assert "HTTP(S)" in result


def test_json_tool_failure_is_never_reported_as_success():
    failed = json.dumps({"ok": False, "data": {}, "error": "blocked", "code": "DENIED"})
    parsed = parse_tool_result(failed)
    assert parsed.ok is False
    assert parsed.error == "blocked"
    assert parsed.code == "DENIED"


def test_stripped_audit_integrity_is_not_resigned_on_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key = "audit-" + "a" * 64
    checkpoint = tmp_path / "checkpoint.json"
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", key)
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", str(checkpoint))
    db = tmp_path / "company.db"
    store = CompanyStore(db)
    store.audit("founder", "create", "task", "1", "allowed", {"safe": True})
    store.close()

    with closing(sqlite3.connect(db)) as connection:
        connection.execute(
            "UPDATE audit_logs SET actor='attacker',prev_hash='',entry_hash='',entry_signature='',signature_key_id='' WHERE sequence=1"
        )
        connection.commit()

    reopened = CompanyStore(db)
    try:
        row = reopened._connection.execute(
            "SELECT entry_hash,entry_signature,signature_key_id FROM audit_logs WHERE sequence=1"
        ).fetchone()
        assert tuple(row) == ("", "", "")
        assert reopened.audit_chain_check()["ok"] is False
        with pytest.raises(RuntimeError, match="automatic repair is forbidden"):
            reopened.audit("worker", "append", "task", "2", "allowed", {})
    finally:
        reopened.close()


def test_desktop_health_challenge_requires_child_secret(monkeypatch: pytest.MonkeyPatch):
    secret = "desktop-" + "b" * 64
    api_key = "api-" + "a" * 64
    challenge = "challenge-" + "c" * 64
    monkeypatch.setenv("AMAURA_DESKTOP_BOOTSTRAP_TOKEN", secret)
    monkeypatch.setenv("JARVIS_API_KEY", api_key)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 403
        response = client.get("/api/health", headers={"X-Amaura-Bootstrap-Challenge": challenge})
        authenticated_response = client.get("/api/health", headers={"X-Jarvis-Key": api_key})
    assert response.status_code == 200
    assert authenticated_response.status_code == 200
    assert authenticated_response.json()["bootstrap_proof"] == ""
    expected = hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    assert response.json()["bootstrap_proof"] == expected


def test_background_service_health_uses_jarvis_key_hmac(monkeypatch: pytest.MonkeyPatch):
    secret = "service-" + "d" * 64
    challenge = "challenge-" + "e" * 64
    monkeypatch.delenv("AMAURA_DESKTOP_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.setenv("JARVIS_API_KEY", secret)
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Amaura-Service-Challenge": challenge})
    assert response.status_code == 200
    expected = hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    assert response.json()["service_proof"] == expected


def test_desktop_package_uses_sidecar_dynamic_port_and_authentication():
    root = Path(__file__).parents[1]
    main = (root / "desktop-app" / "main.js").read_text(encoding="utf-8")
    package = json.loads((root / "desktop-app" / "package.json").read_text(encoding="utf-8"))
    assert "serverPort: 0" in main
    assert "allocateLoopbackPort" in main
    assert "AMAURA_DESKTOP_BOOTSTRAP_TOKEN" in main
    assert "timingSafeEqual" in main
    assert "amaura-backend" in main
    assert "BACKEND_VERSION = '5.4.2'" in main
    assert "tryAttachBackgroundService" in main
    assert "X-Amaura-Service-Challenge" in main
    assert "backendAttached" in main
    assert "app.requestSingleInstanceLock()" in main
    assert "child.exitCode === null" in main
    assert "AMAURA_RESOURCE_PROFILE" in main
    assert package["version"] == "5.4.2"
    assert package["dependencies"] == {}
    assert package["devDependencies"] == {}
    desktop_builder = (root / "scripts" / "build_desktop_app.py").read_text(encoding="utf-8")
    backend_builder = (root / "scripts" / "build_desktop_backend.py").read_text(encoding="utf-8")
    assert "electron_sha256" in desktop_builder
    assert "amaura-backend" in desktop_builder
    assert "PyInstaller" in backend_builder


def test_server_and_desktop_versions_match_current_package():
    root = Path(__file__).parents[1]
    server = (root / "jarvis" / "server.py").read_text(encoding="utf-8")
    package = json.loads((root / "desktop-app" / "package.json").read_text(encoding="utf-8"))
    assert 'version="5.4.2"' in server
    assert package["version"] == "5.4.2"


def test_secret_scan_detects_generic_and_url_credentials(tmp_path: Path):
    generic = "A" * 32
    scheme = "post" + "gres"
    password = "super" + "secret" + "password"
    (tmp_path / "unsafe.py").write_text(
        f'api_key = "{generic}"\nDATABASE_URL = "{scheme}://user:{password}@db.example/app"\n',
        encoding="utf-8",
    )
    report = scan_repository(tmp_path)
    kinds = {item["kind"] for item in report["findings"]}
    assert report["ok"] is False
    assert "generic_secret_assignment" in kinds
    assert "credentialed_url" in kinds
