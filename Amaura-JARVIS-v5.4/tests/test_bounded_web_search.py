from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from jarvis.tools import resilient_research
from jarvis.tools.registry import ALL_DISPATCH


def test_web_search_hard_timeout_becomes_failed_tool_result(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=12)

    monkeypatch.setattr(resilient_research.subprocess, "run", timeout)

    result = resilient_research.tool_web_search("amaura competitors", max_results=5)

    assert result.startswith("❌ Search timed out after 12s")


def test_web_search_uses_bounded_child_and_formats_results(monkeypatch):
    payload = [
        {
            "title": "Example result",
            "href": "https://example.com/research",
            "body": "Evidence snippet",
        }
    ]
    captured = {}

    def completed(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(resilient_research.subprocess, "run", completed)

    result = resilient_research.tool_web_search("bounded query", max_results=99)

    assert "Example result" in result
    assert "https://example.com/research" in result
    assert captured["kwargs"]["timeout"] == 12
    assert captured["kwargs"]["shell"] is False
    assert captured["argv"][0] == resilient_research.sys.executable
    assert captured["argv"][4] == "10"


def test_registry_overrides_legacy_unbounded_search_handlers():
    assert ALL_DISPATCH["web_search"] is resilient_research.tool_web_search
    assert ALL_DISPATCH["deep_research"] is resilient_research.tool_deep_research


def test_deep_research_recovers_when_one_search_times_out(monkeypatch):
    calls = []

    def search(query, max_results=5):
        calls.append(query)
        if len(calls) == 1:
            return [], "Search timed out after 12s"
        return [
            {
                "title": "Source",
                "href": "https://example.com/source",
                "body": "Useful snippet",
            }
        ], None

    monkeypatch.setattr(resilient_research, "_bounded_ddg_results", search)
    monkeypatch.setattr(resilient_research, "_fetch_url_text", lambda url, max_length=3000: "Useful content")

    result = resilient_research.tool_deep_research("AI assistants", num_queries=2)

    assert "# Research Report: AI assistants" in result
    assert "Recovered search failures:** 1" in result
    assert "https://example.com/source" in result
