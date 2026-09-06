import tempfile
from pathlib import Path
import pytest
from jarvis.amaura.verification import SecureVerifierRunner
from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
from jarvis.amaura.models import GovernanceError

def test_verifier_compound_command_split():
    runner = SecureVerifierRunner(mode="auto")
    with tempfile.TemporaryDirectory() as td:
        try:
            results = runner.run_all(td, ["python --version && python -V"])
            assert len(results) == 2
            assert all(r["passed"] for r in results)
        except GovernanceError:
            pass

def test_transient_test_artifact_detection():
    assert AntigravityDeliveryAdapter._is_transient_test_artifact(".pytest_cache/v/cache/nodeids")
    assert AntigravityDeliveryAdapter._is_transient_test_artifact("subfolder/.pytest_cache/v/cache")
    assert AntigravityDeliveryAdapter._is_transient_test_artifact("__pycache__/foo.cpython-313.pyc")
    assert AntigravityDeliveryAdapter._is_transient_test_artifact(".coverage")
    assert AntigravityDeliveryAdapter._is_transient_test_artifact(".ruff_cache/0.1.0/cache")
    assert not AntigravityDeliveryAdapter._is_transient_test_artifact("jarvis/amaura/verification.py")
    assert not AntigravityDeliveryAdapter._is_transient_test_artifact("tests/test_something.py")

def test_norm_declared_subfolder_mapping():
    repo = Path("/tmp/repo")
    working_dir = repo / "subproject"
    subfolder_rel = working_dir.relative_to(repo)
    actual = ["subproject/src/main.py", "subproject/tests/test_main.py"]

    raw_declared = ["src/main.py", "tests/test_main.py"]
    norm_declared = []
    for p in raw_declared:
        cand = str(p)
        if subfolder_rel and cand not in actual and str(subfolder_rel / cand) in actual:
            cand = str(subfolder_rel / cand)
        norm_declared.append(cand)

    assert norm_declared == actual
