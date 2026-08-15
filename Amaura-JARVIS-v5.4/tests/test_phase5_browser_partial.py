"""Phase 5 Tests: Browser Partial Result Truthfulness (Phase 8)."""

import json
from unittest.mock import patch
import pytest

from jarvis.amaura.direct_action import DirectActionRouter


def test_browser_all_fields_succeed():
    """When all compound browser fields succeed, return success=True and combined output."""
    url = "https://example.com/test_success"
    prompt = f"Navigate to {url} and extract the page title and #main-content"

    nav_output = {"ok": True, "data": {"output": {"title": "Example Success Page"}}, "error": None}
    extract_output = {"ok": True, "data": {"output": {"content": "This is the main content."}}, "error": None}

    def mock_execute(tool_name, args):
        if tool_name == "browser_navigate":
            return json.dumps(nav_output)
        elif tool_name == "browser_extract_content":
            return json.dumps(extract_output)
        return json.dumps({"ok": False, "error": "unknown_tool"})

    with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_execute):
        res = DirectActionRouter.execute(prompt)
        assert res is not None
        assert res.success is True
        assert "Example Success Page" in res.output
        assert "This is the main content" in res.output
        assert res.telemetry.get("status") == "completed"
        assert res.telemetry.get("verification_passed") is True


def test_browser_partial_failure_reporting():
    """When 1 field succeeds and 1 fails, report partial failure with details of what succeeded and what failed."""
    url = "https://example.com/test_partial"
    prompt = f"Navigate to {url} and extract the page title and .nonexistent_class"

    nav_output = {"ok": True, "data": {"output": {"title": "My Valid Title"}}, "error": None}
    extract_output = {"ok": True, "data": {"output": {"content": "No elements matched selector"}}, "error": None}

    def mock_execute(tool_name, args):
        if tool_name == "browser_navigate":
            return json.dumps(nav_output)
        elif tool_name == "browser_extract_content":
            return json.dumps(extract_output)
        return json.dumps({"ok": False, "error": "unknown_tool"})

    with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_execute):
        res = DirectActionRouter.execute(prompt)
        assert res is not None
        assert res.success is False  # Must not claim full success
        assert "partially completed" in res.output
        assert "My Valid Title" in res.output
        assert ".nonexistent_class" in res.output
        assert res.telemetry.get("status") == "partial_failure"
        assert "title" in res.telemetry.get("successful_fields", {})
        assert any(".nonexistent_class" in f.get("selector", "") for f in res.telemetry.get("failed_fields", []))


def test_browser_all_fields_missing_reporting():
    """When all requested fields fail, report total failure clearly."""
    url = "https://example.com/test_total_fail"
    prompt = f"Navigate to {url} and extract #missing1 and #missing2"

    nav_output = {"ok": True, "data": {"output": ""}, "error": None}
    extract_output = {"ok": False, "error": "Element not found", "data": {}}

    def mock_execute(tool_name, args):
        if tool_name == "browser_navigate":
            return json.dumps(nav_output)
        elif tool_name == "browser_extract_content":
            return json.dumps(extract_output)
        return json.dumps({"ok": False, "error": "unknown_tool"})

    with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_execute):
        res = DirectActionRouter.execute(prompt)
        assert res is not None
        assert res.success is False
        assert "failed" in res.output.lower()
        assert res.telemetry.get("status") == "total_failure"
