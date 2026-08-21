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


def test_live_semantic_qualifier_uses_fast_bounded_worker_profile():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "qual_semantic_root_live.py"
    source = script.read_text(encoding="utf-8")

    assert '"--max-iterations"' in source
    assert "default=12" in source
    assert "1 <= args.max_iterations <= 20" in source
    assert "max_iterations=args.max_iterations" in source
    assert '"--worker-deadline-seconds"' in source
    assert "default=300" in source
    assert "60 <= args.worker_deadline_seconds <= 600" in source
    assert 'os.environ["AMAURA_NVIDIA_TIMEOUT"] = "15"' in source
    assert 'os.environ["AMAURA_NVIDIA_TOTAL_TIMEOUT"] = "20"' in source
    assert 'os.environ["AMAURA_NVIDIA_MAX_KEY_ATTEMPTS"] = "1"' in source
    assert "signal.setitimer" in source
    assert "WorkerDeadlineExceeded" in source


def test_live_semantic_qualifier_replans_unfinished_worker_retry():
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "qual_semantic_root_live.py"
    source = script.read_text(encoding="utf-8")

    assert 'task["state"] == "in_progress"' in source
    assert 'metadata["replan_instruction"]' in source
    assert "Target 6-8 distinct successful public sources" in source
    assert "stop tool use immediately" in source
    assert "unfinished worker conversation is not checkpointed" in source
