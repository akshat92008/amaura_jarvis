"""
tests/test_omniroute_integration.py
────────────────────────────────────────────────────────────────────
Security, reliability, and regression tests for the OmniRoute
primary cognition gateway integration in Amaura JARVIS v5.4.1.
"""

from __future__ import annotations

import http.server
import json
import os
import threading
from typing import Any
from unittest.mock import patch

import pytest

from jarvis.amaura.model_gateway import CognitiveModelGateway, CognitiveModelResult
from jarvis.amaura.models import GovernanceError


@pytest.fixture()
def omniroute_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:19999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "sk-test-" + "x" * 32)
    monkeypatch.setenv("AMAURA_OMNIROUTE_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    yield


class _MockHTTPHandler(http.server.BaseHTTPRequestHandler):
    _status: int = 200
    _body: dict[str, Any] = {}
    _extra_headers: dict[str, str] = {}

    def do_POST(self):
        self.send_response(self._status)
        self.send_header("Content-Type", "application/json")
        for k, v in self._extra_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(self._body).encode())

    def do_GET(self):
        self.send_response(self._status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self._body).encode())

    def log_message(self, *args, **kwargs):
        pass


class _ReusableHTTPServer(http.server.HTTPServer):
    allow_reuse_address = True


def _run_server(handler_class, port: int):
    server = _ReusableHTTPServer(("127.0.0.1", port), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


# ── Provider Registration ────────────────────────────────────────────────

def test_omniroute_is_in_providers_list():
    assert "omniroute" in CognitiveModelGateway.PROVIDERS

def test_omniroute_is_first_in_providers_list():
    assert CognitiveModelGateway.PROVIDERS[0] == "omniroute"

def test_omniroute_first_in_default_order(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AMAURA_JARVIS_PROVIDER_ORDER", raising=False)
    default = "omniroute,openrouter,openai,anthropic,nvidia,groq,ollama"
    actual = os.environ.get("AMAURA_JARVIS_PROVIDER_ORDER", default)
    order = [p.strip() for p in actual.split(",") if p.strip()]
    assert order.index("omniroute") < order.index("openrouter")


# ── Selection ──────────────────────────────────────────────────────────

def test_omniroute_selected_when_configured(omniroute_env):
    sel = CognitiveModelGateway.select(purpose="general")
    assert sel is not None
    assert sel.provider == "omniroute"
    assert sel.model == "gpt-4o-mini"

def test_omniroute_available_when_configured(omniroute_env):
    assert CognitiveModelGateway.available(purpose="general") is True

def test_omniroute_not_available_without_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:19999")
    monkeypatch.setenv("AMAURA_OMNIROUTE_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("AMAURA_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    assert CognitiveModelGateway.select(purpose="general") is None

def test_omniroute_not_available_without_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "sk-test-" + "x" * 32)
    monkeypatch.setenv("AMAURA_OMNIROUTE_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("AMAURA_OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    assert CognitiveModelGateway.select(purpose="general") is None

def test_omniroute_not_available_without_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "sk-test-" + "x" * 32)
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:19999")
    monkeypatch.delenv("AMAURA_OMNIROUTE_MODEL", raising=False)
    monkeypatch.delenv("OMNIROUTE_MODEL", raising=False)
    monkeypatch.delenv("AMAURA_JARVIS_MODEL", raising=False)
    assert CognitiveModelGateway.select(purpose="general") is None


# ── Status / Health ────────────────────────────────────────────────────

def test_omniroute_status_ready(omniroute_env):
    status = CognitiveModelGateway.status(purpose="general")
    assert status["available"] is True
    assert status["gateway"] == "OmniRoute"
    assert status["status"] == "READY"
    assert status["provider"] == "omniroute"

def test_status_does_not_expose_api_key(omniroute_env):
    fake_key = "sk-test-" + "x" * 32
    status = CognitiveModelGateway.status(purpose="general")
    assert fake_key not in json.dumps(status)


# ── Secret Redaction ───────────────────────────────────────────────────

def test_redact_secrets_removes_key():
    fake_key = "sk-testkey-abc123"
    with patch.dict(os.environ, {"AMAURA_OMNIROUTE_API_KEY": fake_key}):
        result = CognitiveModelGateway._redact_secrets(f"Error with key {fake_key} in msg")
    assert fake_key not in result
    assert "[REDACTED]" in result

def test_redact_secrets_safe_with_empty_keys():
    result = CognitiveModelGateway._redact_secrets("neutral error text")
    assert "neutral error text" in result


# ── Error Classification ───────────────────────────────────────────────

def test_omniroute_raises_on_missing_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AMAURA_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:19999")
    with pytest.raises(GovernanceError, match="not properly configured"):
        CognitiveModelGateway._omniroute(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "test"}],
            temperature=0.1, max_tokens=100,
        )

def test_omniroute_rejects_non_http_base_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "sk-test-" + "x" * 32)
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "ftp://malicious.example.com")
    with pytest.raises(GovernanceError, match="must start with http"):
        CognitiveModelGateway._omniroute(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "test"}],
            temperature=0.1, max_tokens=100,
        )


# ── Successful Round-Trip ──────────────────────────────────────────────

def test_omniroute_successful_response(omniroute_env):
    class SuccessHandler(_MockHTTPHandler):
        _status = 200
        _body = {
            "id": "chatcmpl-abc123",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"role": "assistant", "content": "Hello from JARVIS!"}}],
        }
        _extra_headers = {"x-request-id": "req-xyz", "x-resolved-provider": "openai"}

    server, thread = _run_server(SuccessHandler, 19999)
    try:
        result = CognitiveModelGateway._omniroute(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello?"}],
            temperature=0.2, max_tokens=100,
        )
        assert "JARVIS" in result.text
        assert result.provider == "omniroute"
        assert result.gateway == "omniroute"
        assert result.request_id == "chatcmpl-abc123"
        assert result.resolved_provider == "openai"
        assert result.latency_ms >= 0
        assert result.fallback_used is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


# ── API Key Never Appears in Error ─────────────────────────────────────

def test_omniroute_api_key_never_in_error_messages(omniroute_env):
    fake_key = "sk-test-" + "x" * 32

    class Auth401Handler(_MockHTTPHandler):
        _status = 401
        _body = {"error": {"message": "Unauthorized"}}

    server, thread = _run_server(Auth401Handler, 19999)
    try:
        with pytest.raises(GovernanceError) as exc_info:
            CognitiveModelGateway._omniroute(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.1, max_tokens=100,
            )
        assert fake_key not in str(exc_info.value), "API key leaked in error message"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


# ── Provenance Fields ──────────────────────────────────────────────────

def test_cognitive_model_result_all_provenance_fields():
    r = CognitiveModelResult(
        text="Hello",
        provider="omniroute",
        model="gpt-4o-mini",
        requested_model="gpt-4o",
        resolved_provider="openai",
        resolved_model="gpt-4o-mini",
        fallback_used=True,
        fallback_reason="rate_limit",
        request_id="req-prov-123",
        latency_ms=250,
        gateway="omniroute",
    )
    assert r.gateway == "omniroute"
    assert r.fallback_used is True
    assert r.latency_ms == 250
    assert r.request_id == "req-prov-123"
    assert r.resolved_provider == "openai"


# ── generate() raises without provider ────────────────────────────────

def test_generate_raises_without_any_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AMAURA_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("AMAURA_JARVIS_PROVIDER", raising=False)
    for k in ("AMAURA_OMNIROUTE_API_KEY", "OMNIROUTE_API_KEY", "OPENAI_API_KEY",
              "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AMAURA_JARVIS_ALLOW_OLLAMA", "0")
    with pytest.raises(GovernanceError, match="No configured cognition model"):
        CognitiveModelGateway.generate(
            messages=[{"role": "user", "content": "test"}],
            purpose="general",
        )


# ── Readiness Probe ────────────────────────────────────────────────────

def test_omniroute_readiness_probe_not_configured():
    from jarvis.amaura.readiness import _probe_omniroute
    with patch.dict(os.environ, {}, clear=False):
        for k in ("AMAURA_OMNIROUTE_API_KEY", "OMNIROUTE_API_KEY",
                  "AMAURA_OMNIROUTE_BASE_URL", "OMNIROUTE_BASE_URL"):
            os.environ.pop(k, None)
        result = _probe_omniroute()
    assert result["configured"] is False
    assert result["status"] == "BLOCKED"
    assert result["error"] == "missing_configuration"

def test_omniroute_readiness_probe_does_not_expose_key():
    from jarvis.amaura.readiness import _probe_omniroute
    fake_key = "sk-secret-should-not-appear-" + "z" * 20
    with patch.dict(os.environ, {
        "AMAURA_OMNIROUTE_API_KEY": fake_key,
        "AMAURA_OMNIROUTE_BASE_URL": "http://127.0.0.1:29999",
        "AMAURA_OMNIROUTE_MODEL": "gpt-4o-mini",
    }):
        result = _probe_omniroute()
    assert fake_key not in json.dumps(result), "API key must never appear in readiness probe output"
