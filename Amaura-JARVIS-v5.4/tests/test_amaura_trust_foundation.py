from __future__ import annotations

import hashlib
from contextlib import closing
import hmac
import json
import multiprocessing as mp
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.network import request_json, validate_public_url
from jarvis.amaura.store import CompanyStore
from jarvis.server import app


def _audit_writer(db_path: str, checkpoint: str, key: str, worker: int, count: int) -> None:
    os.environ["AMAURA_AUDIT_HMAC_KEY"] = key
    os.environ["AMAURA_AUDIT_CHECKPOINT_PATH"] = checkpoint
    store = CompanyStore(db_path)
    try:
        for index in range(count):
            store.audit(f"worker-{worker}", "append", "stress", str(index), "allowed", {"index": index})
    finally:
        store.close()


def _slot_writer(db_path: str, opportunity_id: str) -> None:
    store = CompanyStore(db_path)
    try:
        experiment_id = f"exp-{os.getpid()}"
        try:
            store.create_venture_experiment_with_slot(
                {
                    "id": experiment_id,
                    "opportunity_id": opportunity_id,
                    "product_name": experiment_id,
                    "hypothesis": "bounded",
                    "stage": "validating",
                    "timebox_days": 14,
                    "budget_cents": 0,
                    "primary_metric": "users",
                    "target_value": 10.0,
                    "kill_threshold": 1.0,
                },
                max_active=1,
            )
            outcome = 0
        except RuntimeError:
            outcome = 3
    finally:
        store.close()
    raise SystemExit(outcome)


def test_audit_chain_is_atomic_across_processes(tmp_path, monkeypatch):
    db = tmp_path / "company.db"
    checkpoint = tmp_path / "audit-head.json"
    key = "audit-key-" + "a" * 64
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", key)
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", str(checkpoint))
    CompanyStore(db).close()
    ctx = mp.get_context("spawn")
    processes = [ctx.Process(target=_audit_writer, args=(str(db), str(checkpoint), key, worker, 25)) for worker in range(16)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        exitcode = process.exitcode
        process.close()
        assert exitcode == 0
    store = CompanyStore(db)
    try:
        result = store.audit_chain_check()
        assert result["ok"] is True
        assert result["entries"] == 400
        assert result["signed_entries"] == 400
        assert result["checkpoint_ok"] is True
    finally:
        store.close()


def test_recomputed_history_is_rejected_by_hmac_and_checkpoint(tmp_path, monkeypatch):
    db = tmp_path / "company.db"
    checkpoint = tmp_path / "audit-head.json"
    key = "audit-key-" + "b" * 64
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", key)
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", str(checkpoint))
    store = CompanyStore(db)
    store.audit("founder", "create", "task", "1", "allowed", {"safe": True})
    store.audit("worker", "finish", "task", "1", "allowed", {"safe": True})
    store.close()
    # Simulate a database writer rewriting history and recomputing ordinary SHA-256.
    with closing(sqlite3.connect(db)) as connection:
        rows = connection.execute("SELECT sequence,actor,action,resource_type,resource_id,outcome,details,created_at FROM audit_logs ORDER BY sequence").fetchall()
        previous = ""
        for sequence, actor, action, resource_type, resource_id, outcome, details, created_at in rows:
            if sequence == 1:
                actor = "attacker"
                connection.execute("UPDATE audit_logs SET actor=? WHERE sequence=?", (actor, sequence))
            entry = {"actor": actor, "action": action, "resource_type": resource_type, "resource_id": resource_id, "outcome": outcome, "details": details, "created_at": created_at}
            entry_hash = hashlib.sha256((previous + json.dumps(entry, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
            connection.execute("UPDATE audit_logs SET prev_hash=?,entry_hash=? WHERE sequence=?", (previous, entry_hash, sequence))
            previous = entry_hash
        connection.commit()
    store = CompanyStore(db)
    try:
        result = store.audit_chain_check()
        assert result["ok"] is False
        assert result["reason"] in {"signature_invalid", "external_checkpoint_mismatch"}
    finally:
        store.close()


def test_evidence_reference_binds_provenance_and_detects_manifest_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_EVIDENCE_HMAC_KEY", "e" * 64)
    vault = EvidenceVault(tmp_path / "evidence")
    first = vault.put_text("same bytes", source="https://one.example/report", worker_id="worker-a", task_id="task-1")
    second = vault.put_text("same bytes", source="https://two.example/report", worker_id="worker-a", task_id="task-1")
    assert first.sha256 == second.sha256
    assert first.reference != second.reference
    verified = vault.verify(first.reference)
    assert verified["ok"] is True
    assert verified["provenance"]["source"] == "https://one.example/report"
    manifest_path = vault._manifest_path(first.provenance_sha256)
    manifest = json.loads(manifest_path.read_text())
    manifest["source"] = "https://attacker.example/fake"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    assert vault.verify(first.reference)["ok"] is False


def test_request_transport_receives_only_prevalidated_ip(monkeypatch):
    resolver_calls = []

    def resolver(*args, **kwargs):
        resolver_calls.append(args[0])
        return [(2, 1, 6, "", ("93.184.216.34", 80))]

    captured = {}

    def pinned(destination, **kwargs):
        captured["addresses"] = destination.addresses
        return 200, b'{"ok":true}', {"content-type": "application/json"}

    destination = validate_public_url("http://example.com/api", resolver=resolver)
    with patch("jarvis.amaura.network.validate_public_url", return_value=destination), patch("jarvis.amaura.network._pinned_request", side_effect=pinned):
        status, payload, _headers = request_json("http://example.com/api", method="GET")
    assert status == 200 and payload == {"ok": True}
    assert resolver_calls == ["example.com"]
    assert captured["addresses"] == ("93.184.216.34",)


def test_hud_escapes_model_html_and_server_sets_strict_csp(monkeypatch):
    app_js = (Path(__file__).parents[1] / "jarvis" / "static" / "app.js").read_text()
    index_html = (Path(__file__).parents[1] / "jarvis" / "static" / "index.html").read_text()
    assert "marked.parse(content)" not in app_js
    assert "renderSafeMarkdown(content)" in app_js
    assert ".replaceAll(\"<\", \"&lt;\")" in app_js
    assert "https://cdn.jsdelivr.net" not in index_html
    assert "https://cdnjs.cloudflare.com" not in index_html
    with TestClient(app) as client:
        response = client.get("/")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-src 'none'" in csp


def test_local_amaura_reads_require_operator_key(monkeypatch):
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", "operator-secret")
    from jarvis.tools.amaura import reset_control_plane

    try:
        with TestClient(app) as client:
            assert client.get("/api/amaura/dashboard").status_code == 403
            assert client.get("/api/amaura/dashboard", headers={"X-Amaura-Operator-Key": "operator-secret"}).status_code == 200
    finally:
        reset_control_plane()


def test_venture_slot_admission_is_atomic_across_processes(tmp_path):
    db = tmp_path / "company.db"
    store = CompanyStore(db)
    opportunity_id = "opp-1"
    store.create_venture_opportunity({
        "id": opportunity_id,
        "title": "Bounded product",
        "problem": "problem",
        "target_user": "user",
        "product_type": "micro_saas",
        "source": "verified",
        "evidence": [],
        "score_components": {},
        "total_score": 80,
        "estimated_build_days": 7,
        "monetization": "subscription",
        "distribution_channel": "owned",
        "status": "selected",
        "strategic_fit": "fit",
    })
    store.close()
    ctx = mp.get_context("spawn")
    processes = [ctx.Process(target=_slot_writer, args=(str(db), opportunity_id)) for _ in range(12)]
    for process in processes:
        process.start()
    exitcodes = []
    for process in processes:
        process.join(30)
        exitcodes.append(process.exitcode)
        process.close()
    assert exitcodes.count(0) == 1
    assert exitcodes.count(3) == 11
    store = CompanyStore(db)
    try:
        active = [item for item in store.list_venture_experiments(limit=100) if item["stage"] == "validating"]
        assert len(active) == 1
    finally:
        store.close()
