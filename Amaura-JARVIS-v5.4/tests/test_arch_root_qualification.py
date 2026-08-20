from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"test_{name.replace('.', '_')}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E2E = _load_script("qualify_arch_root_e2e.py")
BATCH = _load_script("qualify_arch_company_roots.py")


def test_e2e_extracts_last_worker_evidence_path(tmp_path: Path) -> None:
    first = tmp_path / "a" / "summary.json"
    second = tmp_path / "b" / "summary.json"
    output = f"Evidence: {first}\nnoise\nEvidence: {second}\n"

    assert E2E._extract_summary_path(output) == second.resolve()


def test_e2e_copy_environment_isolated_and_checkpointed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    q = tmp_path / "qualification"
    checkpoint = q / "trust" / "audit-head.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AMAURA_DATA_DIR", "/live/data")
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", "/live/checkpoint.json")

    result = E2E._configure_copy_environment(q)

    assert result == checkpoint.resolve()
    assert os.environ["AMAURA_DATA_DIR"] == str((q / "data").resolve())
    assert os.environ["AMAURA_EVIDENCE_DIR"] == str((q / "evidence").resolve())
    assert os.environ["AMAURA_AUDIT_CHECKPOINT_PATH"] == str(checkpoint.resolve())
    assert os.environ["JARVIS_LEGACY_TOOL_MODE"] == "disabled"
    assert os.environ["JARVIS_ENABLE_LEGACY_DIRECT_TOOLS"] == "0"
    assert os.environ["AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS"] == "0"


def test_batch_action_type_lookup_is_read_only(tmp_path: Path) -> None:
    db = tmp_path / "amaura.db"
    connection = sqlite3.connect(db)
    try:
        connection.execute("CREATE TABLE work_items(id TEXT PRIMARY KEY, action_type TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO work_items(id,action_type) VALUES(?,?)",
            [("safe", "internal_work"), ("unsafe", "send_email")],
        )
        connection.commit()
    finally:
        connection.close()

    before = db.read_bytes()
    result = BATCH._action_types(db, ["safe", "unsafe"])
    after = db.read_bytes()

    assert result == {"safe": "internal_work", "unsafe": "send_email"}
    assert before == after


def test_batch_extract_path_requires_explicit_evidence_line(tmp_path: Path) -> None:
    path = tmp_path / "run" / "e2e-summary.json"
    output = f"E2E Evidence: {path}\n"

    assert BATCH._extract_path(BATCH._E2E_EVIDENCE_LINE, output, "E2E") == path.resolve()

    with pytest.raises(RuntimeError, match="did not report"):
        BATCH._extract_path(BATCH._E2E_EVIDENCE_LINE, "no evidence here", "E2E")
