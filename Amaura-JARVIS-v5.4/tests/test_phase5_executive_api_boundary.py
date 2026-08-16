"""Phase 5 Tests: Executive and API Boundary Tests (Phase 21)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.control_plane import AmauraControlPlane


def test_api_boundary_write_exact():
    """ExecutiveKernel.handle creates and strictly verifies file write."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        target = ws / "api_written.txt"
        content = "Exact API boundary text 987654"
        prompt = f"Create {target}. Its complete content must be: {content}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        req = ExecutiveRequest(text=prompt, session_id="api_write_test", workspace=str(ws))
        resp = kernel.handle(req)

        assert resp is not None
        assert resp.state == "completed"
        assert target.exists()
        assert target.read_text(encoding="utf-8") == content


def test_api_boundary_security_refusal_during_model_outage():
    """ExecutiveKernel.handle enforces security boundaries even when model gateway is completely down."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        outside_target = ws.parent / "forbidden_api_escape.txt"
        prompt = f"Write 'secret' to {outside_target}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        with patch(
            "jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=RuntimeError("Gateway Offline")
        ):
            with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.available", return_value=False):
                req = ExecutiveRequest(text=prompt, session_id="api_sec_test", workspace=str(ws))
                resp = kernel.handle(req)

                assert resp is not None
                assert resp.state == "refused"
                assert "outside workspace" in resp.message.lower() or "workspace" in resp.message.lower()


def test_api_boundary_browser_partial_result():
    """ExecutiveKernel.handle reports partial browser results with precision."""
    url = "https://example.com/api_partial"
    prompt = f"Navigate to {url} and extract the page title and .missing_sel"

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        nav_output = {"ok": True, "data": {"output": {"title": "API Partial Title"}}, "error": None}
        extract_output = {"ok": True, "data": {"output": {"content": "No elements matched selector"}}, "error": None}

        def mock_execute(tool_name, args):
            if tool_name == "browser_navigate":
                return json.dumps(nav_output)
            elif tool_name == "browser_extract_content":
                return json.dumps(extract_output)
            return json.dumps({"ok": False, "error": "unknown_tool"})

        with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_execute):
            req = ExecutiveRequest(text=prompt, session_id="api_browser_test", workspace=str(ws))
            resp = kernel.handle(req)

            assert resp is not None
            assert resp.state == "failed"  # Partial failure does not claim completion
            assert "partially completed" in resp.message
            assert "API Partial Title" in resp.message
            assert ".missing_sel" in resp.message


def test_api_boundary_repo_diagnosis():
    """ExecutiveKernel.handle produces semantic explanation for repository bug."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "math_mod.py"
        src.write_text("""
def calculate_sum(a: int, b: int) -> int:
    '''Sum two integers.'''
    return a - b
""")
        test_file = repo / "test_math_mod.py"
        test_file.write_text("""
from math_mod import calculate_sum

def test_sum():
    assert calculate_sum(20, 10) == 30
""")
        control = AmauraControlPlane(repo / "control")
        kernel = ExecutiveKernel(control)

        prompt = f"Inspect repository at {repo} and diagnose the defect"
        req = ExecutiveRequest(text=prompt, session_id="api_repo_test", workspace=str(repo))
        resp = kernel.handle(req)

        assert resp is not None
        assert resp.state == "completed"
        assert "calculate_sum" in resp.message
        assert "subtract" in resp.message.lower() or "defect" in resp.message.lower()


def test_api_boundary_tsv_workflow():
    """ExecutiveKernel.handle executes TSV table transformation workflow end-to-end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        tsv_file = ws / "data.tsv"
        json_file = ws / "data.json"

        tsv_file.write_text("item\tcount\napple\t10\nbanana\t25\n")

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        prompt = f"Read table {tsv_file} and save transformed JSON in {json_file}"
        req = ExecutiveRequest(text=prompt, session_id="api_workflow_test", workspace=str(ws))
        resp = kernel.handle(req)

        assert resp is not None
        assert resp.state == "completed"
        assert json_file.exists()

        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0] == {"item": "apple", "count": 10}
        assert data[1] == {"item": "banana", "count": 25}


def test_api_boundary_exact_response_burst():
    """ExecutiveKernel.handle responds to exact echo commands with 0 model calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        def mock_generate(*args, **kwargs):
            raise RuntimeError("Model should not be invoked for exact echo")

        with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=mock_generate):
            for i in range(10):
                expected = f"API_EXACT_TOKEN_{i}"
                prompt = f"Your entire reply must be this value and nothing else: {expected}"
                req = ExecutiveRequest(text=prompt, session_id="api_echo_test", workspace=str(ws))
                resp = kernel.handle(req)
                assert resp is not None
                assert resp.message == expected
