import json
import ssl

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


def test_pinned_https_connection_uses_certifi_bundle(monkeypatch):
    captured: dict[str, str] = {}

    def context(*, cafile: str):
        captured["cafile"] = cafile
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(network.ssl, "create_default_context", context)
    monkeypatch.setattr(network.certifi, "where", lambda: "/trusted/cacert.pem")

    network._PinnedHTTPSConnection("example.com", "93.184.216.34", 443, timeout=1)

    assert captured["cafile"] == "/trusted/cacert.pem"
