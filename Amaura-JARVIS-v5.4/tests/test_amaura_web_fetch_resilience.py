import json

from jarvis.amaura import network
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.models import GovernanceError
from jarvis.tools.result import parse_tool_result


def test_public_text_fetch_converts_governance_failure_to_failed_evidence_marker(monkeypatch):
    def fail_fetch(_url: str, *, max_length: int):
        raise GovernanceError("Outbound hostname could not be resolved: hallucinated.example")

    monkeypatch.setattr(network, "fetch_public_bytes", fail_fetch)

    result = network.fetch_public_text("https://hallucinated.example")

    assert result == "❌ Outbound hostname could not be resolved: hallucinated.example"


def test_governed_web_fetch_returns_structured_failure_instead_of_escaping(monkeypatch):
    monkeypatch.setattr(
        "jarvis.amaura.executor.fetch_public_text",
        lambda _url, *, max_length: "❌ Outbound hostname could not be resolved: hallucinated.example",
    )
    runner = object.__new__(GovernedTaskRunner)

    raw = runner._execute_tool(
        "web_fetch",
        {"url": "https://hallucinated.example", "max_length": 10_000},
        execute_tool=lambda *_args, **_kwargs: "unused",
    )
    decoded = json.loads(raw)
    parsed = parse_tool_result(raw)

    assert decoded["ok"] is False
    assert decoded["retryable"] is False
    assert parsed.ok is False
    assert "hallucinated.example" in (parsed.error or "")
