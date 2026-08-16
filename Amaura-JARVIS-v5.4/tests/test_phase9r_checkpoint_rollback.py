from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jarvis.amaura.store import CompanyStore


def _remove_sqlite_sidecars(db: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def test_strict_external_checkpoint_blocks_database_rollback_before_new_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint ahead of the DB must fail closed before history can fork.

    This models restoring an older database snapshot while leaving the external
    checkpoint at the newer sequence. Internal hashes/signatures in the old
    snapshot are still valid, so only the external anchor can detect rollback.
    """

    db = tmp_path / "company.db"
    checkpoint = tmp_path / "audit-head.json"
    snapshot = tmp_path / "company.snapshot.db"

    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", "phase9r-audit-key-" + "a" * 48)
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("AMAURA_STRICT_AUDIT_SIGNATURES", "1")
    monkeypatch.setenv("AMAURA_STRICT_AUDIT_CHECKPOINT", "1")
    monkeypatch.setenv("AMAURA_REQUIRE_EXTERNAL_AUDIT_CHECKPOINT", "1")

    with CompanyStore(db) as store:
        store.audit("operator", "first", "test", "1", "allowed", {"step": 1})
    _remove_sqlite_sidecars(db)
    shutil.copy2(db, snapshot)

    with CompanyStore(db) as store:
        store.audit("operator", "second", "test", "2", "allowed", {"step": 2})
        assert store.audit_chain_check()["ok"] is True

    _remove_sqlite_sidecars(db)
    shutil.copy2(snapshot, db)
    _remove_sqlite_sidecars(db)

    with CompanyStore(db) as rolled_back:
        check = rolled_back.audit_chain_check()
        assert check["ok"] is False
        assert check["reason"] == "external_checkpoint_mismatch"
        with pytest.raises(RuntimeError, match="checkpoint|integrity|rollback"):
            rolled_back.audit("operator", "must_not_append", "test", "3", "allowed", {"step": 3})
