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
