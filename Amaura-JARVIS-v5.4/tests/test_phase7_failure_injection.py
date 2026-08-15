"""Phase 7 Test Suite 9: Failure Injection and Truthful Error Reporting."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.direct_action import (
    DirectActionRouter,
    WriteActionParser,
    ExactResponseParser,
    RepositoryDiagnosticEngine,
)


def test_failure_injection_ambiguous_write_payload():
    """Ambiguous write payload must fail closed with truthful refusal."""
    prompt = 'write to /tmp/ambiguous.txt either "option_alpha" or "option_beta"'
    action = WriteActionParser.parse(prompt)
    assert action is not None
    assert action.is_invalid is True
    assert "Ambiguous" in action.invalid_reason or "ambiguous" in action.invalid_reason

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)
        req = ExecutiveRequest(text=prompt, session_id="fail_ambig_write", workspace=str(ws))
        resp = kernel.handle(req)
        assert resp is not None
        assert "Write action rejected" in resp.message or resp.state in ("failed", "refused")


def test_failure_injection_missing_write_output():
    """Simulate tool reporting success while file was not actually written."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        target = ws / "phantom.txt"
        prompt = f"Create {target}. Its content must be: Real content"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        # Mock write_file to do nothing
        def mock_write(tool_name, args):
            if tool_name == "write_file":
                return json.dumps({"ok": True, "data": {"output": "written"}})
            return json.dumps({"ok": False, "error": "unknown"})

        with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_write):
            req = ExecutiveRequest(text=prompt, session_id="fail_missing_write", workspace=str(ws))
            resp = kernel.handle(req)
            assert resp is not None
            assert resp.state == "failed"
            assert "verification failed" in resp.message.lower() or "missing" in resp.message.lower()


def test_failure_injection_post_write_byte_corruption():
    """Simulate post-write file corruption (e.g. truncated or altered bytes)."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        target = ws / "corrupt.txt"
        expected = "Original pure content 123456"
        prompt = f"Create {target}. Its content must be: {expected}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        # Mock write_file to write corrupted content
        def mock_corrupt_write(tool_name, args):
            if tool_name == "write_file":
                target.write_text("CORRUPTED_BYTES_DIFFERENT", encoding="utf-8")
                return json.dumps({"ok": True, "data": {"output": "written"}})
            return json.dumps({"ok": False, "error": "unknown"})

        with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_corrupt_write):
            req = ExecutiveRequest(text=prompt, session_id="fail_corrupt_write", workspace=str(ws))
            resp = kernel.handle(req)
            assert resp is not None
            assert resp.state == "failed"
            assert "mismatch" in resp.message.lower() or "failed" in resp.message.lower()


def test_failure_injection_screenshot_permission_denial():
    """Screenshot tool failing with macOS permission denial returns truthful failure."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        target = ws / "shot.png"
        prompt = f"take a screenshot and save to {target}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        def mock_perm_denied(tool_name, args):
            return json.dumps({"ok": False, "error": "screencapture: Screen Recording permission denied by system"})

        with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_perm_denied):
            req = ExecutiveRequest(text=prompt, session_id="fail_perm_shot", workspace=str(ws))
            resp = kernel.handle(req)
            assert resp is not None
            assert resp.state in ("failed", "refused")
            assert "permission" in resp.message.lower() or "denied" in resp.message.lower() or "failed" in resp.message.lower()


def test_failure_injection_negated_action():
    """Negated screenshot must not execute screenshot tool."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        prompt = "do not take a screenshot"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        executed_tools = []
        def mock_track_tools(tool_name, args):
            executed_tools.append(tool_name)
            return json.dumps({"ok": True, "data": {}})

        with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_track_tools):
            req = ExecutiveRequest(text=prompt, session_id="fail_negated", workspace=str(ws))
            resp = kernel.handle(req)
            assert "take_screenshot" not in executed_tools


def test_failure_injection_workflow_missing_input():
    """Workflow with nonexistent input file truthfully reports FileNotFoundError."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        f1 = ws / "nonexistent_a.num"
        f2 = ws / "nonexistent_b.num"
        out = ws / "out.num"
        prompt = f"take the number in {f1} away from {f2} and save to {out}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        req = ExecutiveRequest(text=prompt, session_id="fail_wf_missing", workspace=str(ws))
        resp = kernel.handle(req)
        assert resp is not None
        assert resp.state == "failed"
        assert "not found" in resp.message.lower() or "missing" in resp.message.lower()


def test_failure_injection_raw_read_missing_file():
    """Raw file read on nonexistent file returns truthful failure."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        missing_file = ws / "ghost_file.txt"
        prompt = f"give me raw contents of {missing_file}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        req = ExecutiveRequest(text=prompt, session_id="fail_read_missing", workspace=str(ws))
        resp = kernel.handle(req)
        assert resp is not None
        assert resp.state == "failed"
        assert "not found" in resp.message.lower()


def test_failure_injection_unknown_repo_semantic_defect():
    """When test fails but deterministic AST analysis cannot prove the bug, report truthful unknown."""
    with tempfile.TemporaryDirectory(prefix="unknown_bug_") as td:
        repo_p = Path(td)
        # Obscure defect where code calls complex external logic not covered by AST rules
        (repo_p / "complex.py").write_text("""def compute_complex(data):
    # Some opaque calculation
    res = len(data) * 7
    return res
""")
        (repo_p / "test_complex.py").write_text("""from complex import compute_complex
def test_complex():
    # Assertion that fails with opaque value
    assert compute_complex([1, 2]) == 99999
""")
        res = RepositoryDiagnosticEngine.diagnose(repo_p)
        assert res["read_only_verified"] is True
        findings = res["findings"]
        assert len(findings) > 0
        top = findings[0]
        assert top["category"] == "unresolved_semantic_defect"
        assert "unresolved" in top["description"]
