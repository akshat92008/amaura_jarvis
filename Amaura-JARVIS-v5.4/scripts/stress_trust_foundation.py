#!/usr/bin/env python3
"""Independent multi-process stress for audit, Ventures admission, and evidence provenance."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import sqlite3
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.store import CompanyStore


def audit_writer(db: str, checkpoint: str, key: str, worker: int, count: int) -> None:
    os.environ["AMAURA_AUDIT_HMAC_KEY"] = key
    os.environ["AMAURA_AUDIT_CHECKPOINT_PATH"] = checkpoint
    with CompanyStore(db) as store:
        for index in range(count):
            store.audit(f"worker-{worker}", "stress_append", "trust", str(index), "allowed", {"worker": worker, "index": index})


def slot_writer(db: str, opportunity_id: str) -> None:
    with CompanyStore(db) as store:
        try:
            store.create_venture_experiment_with_slot(
                {
                    "id": f"exp-{os.getpid()}", "opportunity_id": opportunity_id,
                    "product_name": f"product-{os.getpid()}", "hypothesis": "bounded",
                    "stage": "validating", "timebox_days": 14, "budget_cents": 0,
                    "primary_metric": "validated_users", "target_value": 10.0,
                    "kill_threshold": 1.0,
                },
                max_active=1,
            )
        except RuntimeError:
            raise SystemExit(3)
    raise SystemExit(0)


def main() -> int:
    ctx = mp.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="amaura-trust-stress-") as tmp:
        root = Path(tmp)
        db = root / "company.db"
        checkpoint = root / "audit-head.json"
        audit_key = "audit-" + "a" * 64
        evidence_key = "e" * 64
        os.environ.update({
            "AMAURA_AUDIT_HMAC_KEY": audit_key,
            "AMAURA_AUDIT_CHECKPOINT_PATH": str(checkpoint),
            "AMAURA_STRICT_AUDIT_SIGNATURES": "1",
            "AMAURA_STRICT_AUDIT_CHECKPOINT": "1",
            "AMAURA_EVIDENCE_HMAC_KEY": evidence_key,
        })
        CompanyStore(db).close()
        workers = [ctx.Process(target=audit_writer, args=(str(db), str(checkpoint), audit_key, i, 20)) for i in range(32)]
        for process in workers:
            process.start()
        for process in workers:
            process.join(45)
            if process.exitcode != 0:
                raise RuntimeError(f"audit worker failed: {process.pid} exit={process.exitcode}")
            process.close()
        with CompanyStore(db) as store:
            chain = store.audit_chain_check()
        if not chain["ok"] or chain["entries"] != 640 or chain["signed_entries"] != 640:
            raise RuntimeError(f"audit chain stress failed: {chain}")

        # Rewrite ordinary hashes without the HMAC key: verification must fail.
        with sqlite3.connect(db) as connection:
            rows = connection.execute("SELECT sequence,actor,action,resource_type,resource_id,outcome,details,created_at FROM audit_logs ORDER BY sequence").fetchall()
            previous = ""
            for sequence, actor, action, resource_type, resource_id, outcome, details, created_at in rows:
                if sequence == 1:
                    actor = "attacker"
                entry = {"actor": actor, "action": action, "resource_type": resource_type, "resource_id": resource_id, "outcome": outcome, "details": details, "created_at": created_at}
                digest = hashlib.sha256((previous + json.dumps(entry, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
                connection.execute("UPDATE audit_logs SET actor=?,prev_hash=?,entry_hash=? WHERE sequence=?", (actor, previous, digest, sequence))
                previous = digest
            connection.commit()
        with CompanyStore(db) as store:
            tamper = store.audit_chain_check()
        if tamper["ok"]:
            raise RuntimeError("rewritten audit history was accepted")

        venture_db = root / "ventures.db"
        opportunity_id = "opp-stress"
        with CompanyStore(venture_db) as store:
            store.create_venture_opportunity({
                "id": opportunity_id, "title": "Bounded product", "problem": "Verified problem",
                "target_user": "developers", "product_type": "micro_saas", "source": "verified",
                "evidence": [], "score_components": {}, "total_score": 80,
                "estimated_build_days": 7, "monetization": "subscription",
                "distribution_channel": "owned", "status": "selected", "strategic_fit": "fit",
            })
        contenders = [ctx.Process(target=slot_writer, args=(str(venture_db), opportunity_id)) for _ in range(32)]
        for process in contenders:
            process.start()
        codes = []
        for process in contenders:
            process.join(45)
            codes.append(process.exitcode)
            process.close()
        if codes.count(0) != 1 or codes.count(3) != 31:
            raise RuntimeError(f"venture slot race failed: {codes}")

        vault = EvidenceVault(root / "evidence")
        first = vault.put_text("same bytes", source="https://one.example/report", worker_id="worker-a", task_id="task-a")
        second = vault.put_text("same bytes", source="https://two.example/report", worker_id="worker-a", task_id="task-a")
        if first.reference == second.reference or not vault.verify(first.reference)["ok"]:
            raise RuntimeError("provenance identity failed")
        manifest_path = vault._manifest_path(first.provenance_sha256)
        manifest = json.loads(manifest_path.read_text())
        manifest["source"] = "https://attacker.example/fake"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
        if vault.verify(first.reference)["ok"]:
            raise RuntimeError("tampered provenance manifest was accepted")

        print(json.dumps({
            "ok": True,
            "audit_processes": 32,
            "audit_entries": 640,
            "audit_chain_signed": True,
            "history_rewrite_detected": True,
            "venture_contenders": 32,
            "venture_started": 1,
            "venture_blocked": 31,
            "provenance_separation": True,
            "provenance_tamper_detected": True,
        }, indent=2))
    return 0


if __name__ == "__main__":
    code = main()
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
