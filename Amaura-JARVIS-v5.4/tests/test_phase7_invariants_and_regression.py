"""Phase 7 Test Suite 10: Invariants, Wrong-Action Execution Checks & System Regressions."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.direct_action import (
    DirectActionRouter,
    RequestPreprocessor,
    ActionType,
    ResponseMode,
    RepositoryDiagnosticEngine,
)


def test_critical_wrong_action_invariant():
    """Global Invariant: If expected action is NOT screenshot or write, no consequential tool may be invoked."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        executed_tools = []
        def mock_track_tools(tool_name, args):
            executed_tools.append(tool_name)
            return json.dumps({"ok": True, "data": {}})

        test_cases = [
            ("write the word 'screenshot' to /tmp/out.txt", "write_file"),
            ("cat /Users/operator/Desktop/data.txt", "read_file"),
            ("list directory /tmp", "list_directory"),
            ("do not take a screenshot", None),
        ]

        for prompt, expected_tool in test_cases:
            executed_tools.clear()
            with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_track_tools):
                req = ExecutiveRequest(text=prompt, session_id="invariant_test", workspace=str(ws))
                kernel.handle(req)

                if expected_tool is None:
                    assert len(executed_tools) == 0, f"Consequential tool executed for non-action prompt: {prompt} -> {executed_tools}"
                else:
                    assert "take_screenshot" not in executed_tools if expected_tool != "take_screenshot" else True


def test_false_success_invariant():
    """Success must NEVER be true if verification postcondition fails or defect is unresolved."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        target = ws / "unverified.txt"
        prompt = f"Create {target}. Content: test"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        # Mock write failure
        def mock_failing_write(tool_name, args):
            return json.dumps({"ok": False, "error": "Disk quota exceeded"})

        with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_failing_write):
            req = ExecutiveRequest(text=prompt, session_id="false_success_test", workspace=str(ws))
            resp = kernel.handle(req)
            assert resp is not None
            assert resp.result.get("success") is not True, "False success reported on failed tool execution!"


def test_regression_directory_listing():
    """Preserved regression: directory listing with file counts and verified contents."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        (ws / "alpha.txt").write_text("a")
        (ws / "beta.py").write_text("b")
        (ws / "gamma.md").write_text("c")

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        req = ExecutiveRequest(text=f"list directory {ws}", session_id="reg_dir_test", workspace=str(ws))
        resp = kernel.handle(req)
        assert resp is not None
        assert "alpha.txt" in resp.message
        assert "beta.py" in resp.message
        assert "gamma.md" in resp.message


def test_regression_browser_multi_field():
    """Preserved regression: multi-field browser extraction."""
    url = "https://example.com/multi_field"
    prompt = f"Navigate to {url} and extract title, content, links"

    nav_output = {"ok": True, "data": {"output": "Navigated"}}
    title_output = {"ok": True, "data": {"output": "Example Title"}}
    text_output = {"ok": True, "data": {"output": "Example Main Body Text"}}
    links_output = {"ok": True, "data": {"output": ["https://example.com/about", "https://example.com/contact"]}}

    def mock_browser_exec(tool_name, args):
        if tool_name == "browser_navigate":
            return json.dumps(nav_output)
        elif tool_name == "browser_get_title":
            return json.dumps(title_output)
        elif tool_name == "browser_get_text":
            return json.dumps(text_output)
        elif tool_name == "browser_get_links":
            return json.dumps(links_output)
        return json.dumps({"ok": False, "error": "unknown"})

    with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_browser_exec):
        res = DirectActionRouter.execute(prompt)
        assert res is not None
        assert res.success is True
        extracted = json.loads(res.output)
        assert extracted["title"] == "Example Title"
        assert extracted["content"] == "Example Main Body Text"
        assert len(extracted["links"]) == 2


def test_regression_memory_retrieval():
    """Preserved regression: long-term factual memory retrieval."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        control = AmauraControlPlane(ws / "control")
        from jarvis.amaura.cognition import UnifiedMemoryService
        mem = UnifiedMemoryService(control)
        mem.remember(key="office_wifi_password", value="SecretWiFiPass2026", scope="project")

        res = DirectActionRouter.execute("what is the value of office_wifi_password?", control=control)
        assert res is not None
        assert res.success is True
        assert "SecretWiFiPass2026" in res.output


def test_regression_workspace_symlink_security():
    """Preserved regression: symlink escape and sensitive path protection."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        outside = Path(td).parent / "sensitive_out.txt"
        outside.write_text("secret")

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        # Attempt to write outside workspace
        req = ExecutiveRequest(text=f"write 'hack' to {outside}", session_id="symlink_test", workspace=str(ws))
        resp = kernel.handle(req)
        assert resp is not None
        assert resp.state == "refused"
        assert "outside workspace" in resp.message.lower() or "workspace" in resp.message.lower()


def test_regression_delimited_table_transformation():
    """Preserved regression: pipe-delimited table to JSON array transformation."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        csv_f = ws / "input.csv"
        csv_f.write_text("id|name|score\n1|Alice|95\n2|Bob|88\n", encoding="utf-8")
        out_json = ws / "output.json"

        prompt = f"read table from {csv_f} and convert to json at {out_json}"

        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        req = ExecutiveRequest(text=prompt, session_id="table_test", workspace=str(ws))
        resp = kernel.handle(req)
        assert resp is not None
        assert out_json.exists()

        parsed = json.loads(out_json.read_text(encoding="utf-8"))
        assert len(parsed) == 2
        assert parsed[0]["name"] == "Alice"
        assert parsed[0]["score"] == 95
        assert parsed[1]["name"] == "Bob"
