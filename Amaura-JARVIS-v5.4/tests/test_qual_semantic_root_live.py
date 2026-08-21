from __future__ import annotations

import importlib
import runpy
import sys
from pathlib import Path


def test_live_semantic_qualifier_bootstraps_project_root_for_standalone_execution():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "qual_semantic_root_live.py"
    root_text = str(root)
    original_path = list(sys.path)

    try:
        sys.path[:] = [entry for entry in sys.path if entry != root_text]
        assert root_text not in sys.path

        runpy.run_path(str(script), run_name="qual_semantic_root_live_import_test")

        assert sys.path[0] == root_text
        module = importlib.import_module("jarvis.amaura.control_plane")
        assert hasattr(module, "AmauraControlPlane")
    finally:
        sys.path[:] = original_path


def test_live_semantic_qualifier_uses_extended_bounded_worker_budget():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "qual_semantic_root_live.py"
    source = script.read_text(encoding="utf-8")

    assert '"--max-iterations"' in source
    assert "default=20" in source
    assert "1 <= args.max_iterations <= 30" in source
    assert "max_iterations=args.max_iterations" in source
    assert "max_iterations=8" not in source


def test_live_semantic_qualifier_replans_unfinished_worker_retry():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "qual_semantic_root_live.py"
    source = script.read_text(encoding="utf-8")

    assert 'task["state"] == "in_progress"' in source
    assert 'metadata["replan_instruction"]' in source
    assert "target roughly 6-10 successful" in source
    assert "public sources" in source
    assert "unfinished worker conversation is not checkpointed" in source
