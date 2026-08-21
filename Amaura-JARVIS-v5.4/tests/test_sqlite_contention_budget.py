from __future__ import annotations

from jarvis.amaura.store import CompanyStore


def test_company_store_uses_production_busy_timeout_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AMAURA_SQLITE_BUSY_TIMEOUT_MS", raising=False)
    with CompanyStore(tmp_path / "company.db") as store:
        assert store._sqlite_busy_timeout_ms == 30_000
        assert store._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000


def test_company_store_busy_timeout_is_configurable_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_SQLITE_BUSY_TIMEOUT_MS", "2500")
    with CompanyStore(tmp_path / "company.db") as store:
        assert store._sqlite_busy_timeout_ms == 2_500
        assert store._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 2_500

    monkeypatch.setenv("AMAURA_SQLITE_BUSY_TIMEOUT_MS", "999999")
    with CompanyStore(tmp_path / "bounded.db") as store:
        assert store._sqlite_busy_timeout_ms == 120_000
        assert store._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 120_000


def test_company_store_invalid_busy_timeout_falls_back_safely(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_SQLITE_BUSY_TIMEOUT_MS", "not-an-int")
    with CompanyStore(tmp_path / "company.db") as store:
        assert store._sqlite_busy_timeout_ms == 30_000
        assert store._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
