import tempfile
from pathlib import Path
import pytest
from jarvis.verification.closed_loop import (
    verify_python_syntax,
    verify_html_syntax,
    verify_json_syntax,
    verify_file,
    post_tool_closed_loop_verify,
)
from jarvis.tools.advanced_coding import _gen_react_app, _gen_vue_app

def test_verify_python_valid():
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    report = verify_python_syntax(code)
    assert report.passed
    assert report.file_type == "Python"

def test_verify_python_syntax_error():
    code = "def add(a: int, b: int)\n    return a + b\n"
    report = verify_python_syntax(code)
    assert not report.passed
    assert "SyntaxError" in report.details

def test_verify_html_valid():
    html = "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
    report = verify_html_syntax(html)
    assert report.passed

def test_verify_html_mismatched_tags():
    html = "<div><p>Unclosed paragraph</div>"
    report = verify_html_syntax(html)
    assert not report.passed
    assert len(report.errors) > 0

def test_verify_json_valid():
    assert verify_json_syntax('{"ok": true, "count": 42}').passed
    assert not verify_json_syntax('{"ok": true, broken}').passed

def test_post_tool_closed_loop_verify_catches_broken_file():
    with tempfile.TemporaryDirectory() as td:
        broken_file = Path(td) / "broken.py"
        broken_file.write_text("def broken(: pass", encoding="utf-8")
        out, ok = post_tool_closed_loop_verify(
            "write_file",
            {"path": str(broken_file)},
            "Wrote file successfully",
            cwd=td,
        )
        assert not ok
        assert "CLOSED-LOOP VERIFICATION FAILED" in out

def test_gen_react_app_standalone_cap():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "test_react"
        _gen_react_app(base, "StoreApp", "E-commerce store", [])
        index_html = (base / "index.html").read_text(encoding="utf-8")
        assert "StoreApp" in index_html
        assert "Live Web Application" in index_html
        assert "cart" in index_html.lower()
        # Ensure it works under file:// without white screen
        assert 'if (window.location.protocol !== "file:")' not in index_html
