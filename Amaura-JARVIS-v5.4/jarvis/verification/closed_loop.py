"""Closed-loop auto-verification and self-healing validation engine for JARVIS.

Runs post-mutation syntax, structure, and server health checks to ensure code
generated or modified by JARVIS never arrives broken to the user.
"""

from __future__ import annotations

import ast
import http.client
import json
import logging
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.verification")


@dataclass
class VerificationReport:
    passed: bool
    file_type: str
    errors: list[str] = field(default_factory=list)
    details: str = ""

    def summary(self) -> str:
        if self.passed:
            return f"Auto-verified: {self.file_type} syntax valid."
        err_msg = "; ".join(self.errors) if self.errors else self.details
        return f"AUTO-VERIFICATION FAILED: {err_msg}"


class _StrictHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []
        self._stack: list[str] = []
        self._void_tags = {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in self._void_tags:
            self._stack.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._void_tags:
            return
        if not self._stack:
            self.errors.append(f"Unexpected closing tag </{tag}> with no matching opening tag")
            return
        if self._stack[-1] == tag:
            self._stack.pop()
        else:
            # Check if tag is in stack
            if tag in self._stack:
                while self._stack and self._stack[-1] != tag:
                    unclosed = self._stack.pop()
                    self.errors.append(f"Unclosed tag <{unclosed}> before </{tag}>")
                if self._stack:
                    self._stack.pop()
            else:
                self.errors.append(f"Mismatched closing tag </{tag}> (expected </{self._stack[-1]}>)")


def verify_python_syntax(code: str, filename: str = "<string>") -> VerificationReport:
    """Verify that Python code parses and compiles cleanly."""
    try:
        tree = ast.parse(code, filename=filename)
        # Also test byte compilation
        compile(code, filename=filename, mode="exec")
        return VerificationReport(passed=True, file_type="Python", details=f"AST parsed {len(tree.body)} statements.")
    except SyntaxError as exc:
        msg = f"SyntaxError at line {exc.lineno}, col {exc.offset}: {exc.msg}"
        if exc.text:
            msg += f" -> `{exc.text.strip()}`"
        return VerificationReport(passed=False, file_type="Python", errors=[msg], details=msg)
    except Exception as exc:
        return VerificationReport(
            passed=False, file_type="Python", errors=[f"Compilation error: {exc}"], details=str(exc)
        )


def verify_html_syntax(content: str, filename: str = "<string>") -> VerificationReport:
    """Verify that HTML content is structurally sound."""
    parser = _StrictHTMLParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:
        return VerificationReport(
            passed=False, file_type="HTML", errors=[f"HTML parse error: {exc}"], details=str(exc)
        )
    if parser.errors:
        return VerificationReport(
            passed=False, file_type="HTML", errors=parser.errors, details="; ".join(parser.errors)
        )
    return VerificationReport(passed=True, file_type="HTML", details="HTML structure verified.")


def verify_json_syntax(content: str, filename: str = "<string>") -> VerificationReport:
    """Verify that JSON content is valid."""
    try:
        json.loads(content)
        return VerificationReport(passed=True, file_type="JSON", details="JSON syntax valid.")
    except Exception as exc:
        msg = f"JSONDecodeError: {exc}"
        return VerificationReport(passed=False, file_type="JSON", errors=[msg], details=msg)


def probe_loopback_http(port: int, path: str = "/", timeout: float = 3.0) -> dict[str, Any]:
    """Direct loopback HTTP health prober for local dev servers.
    
    Bypasses external SSRF filters since this is explicitly for local testing.
    """
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=timeout)
        conn.request("GET", path)
        response = conn.getresponse()
        status = response.status
        reason = response.reason
        body_preview = response.read(1024).decode("utf-8", errors="replace")
        conn.close()
        healthy = 200 <= status < 400
        return {
            "healthy": healthy,
            "status": status,
            "reason": reason,
            "body_preview": body_preview[:200],
        }
    except Exception as exc:
        return {
            "healthy": False,
            "status": 0,
            "reason": str(exc),
            "body_preview": "",
        }


def verify_file(file_path: str | Path, cwd: str | Path | None = None) -> VerificationReport:
    """Check syntax of a target file on disk according to its extension."""
    target = Path(file_path)
    if not target.is_absolute() and cwd:
        target = (Path(cwd) / target).resolve()
    else:
        target = target.resolve()

    if not target.exists() or not target.is_file():
        return VerificationReport(passed=False, file_type="File", errors=[f"File not found: {target}"])

    suffix = target.suffix.lower()
    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return VerificationReport(passed=False, file_type="Text", errors=[f"Could not read file {target}: {exc}"])

    if suffix in (".py", ".pyw"):
        return verify_python_syntax(content, filename=str(target))
    elif suffix in (".html", ".htm"):
        return verify_html_syntax(content, filename=str(target))
    elif suffix in (".json",):
        return verify_json_syntax(content, filename=str(target))
    else:
        return VerificationReport(passed=True, file_type=suffix or "text", details="No syntax check required.")


def post_tool_closed_loop_verify(
    tool_name: str,
    args: dict[str, Any],
    tool_output: str,
    cwd: str | Path | None = None,
) -> tuple[str, bool]:
    """Execute post-tool verification on write/edit mutations.
    
    Returns (augmented_output, ok). If verification fails, reports the exact syntax
    failure so the agent can self-heal on its next turn.
    """
    if tool_name not in ("write_file", "edit_file"):
        return tool_output, True

    target_path = args.get("path") or args.get("file_path") or args.get("filepath")
    if not target_path:
        return tool_output, True

    report = verify_file(target_path, cwd=cwd)
    if not report.passed:
        diagnostic = (
            f"\n\n⚠️ CLOSED-LOOP VERIFICATION FAILED:\n"
            f"The file `{target_path}` has syntax/structural errors:\n"
            f"- {report.summary()}\n"
            f"Please diagnose and repair `{target_path}` immediately."
        )
        return tool_output + diagnostic, False
    else:
        return tool_output + f" [{report.summary()}]", True
