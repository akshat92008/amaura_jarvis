from __future__ import annotations

import sys
import types

import pytest

from jarvis.amaura.models import GovernanceError
from jarvis.arch_provider_resilience import _enabled_for, _fallback_specs, _hosted_fallback


def test_arch_hosted_failover_is_interactive_only_and_never_local(monkeypatch):
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_COGNITION_FAILOVER", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")

    assert _enabled_for("general") is True
    assert _enabled_for("planner") is False
    providers = [item[0] for item in _fallback_specs()]
    assert providers == ["nvidia", "groq"]
    assert "ollama" not in providers


def test_hosted_fallback_returns_truthful_provider_provenance(monkeypatch):
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    class FakeMessage:
        content = "Hosted fallback answer"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]
        model = "meta/llama-3.3-70b-instruct"

    class FakeCompletions:
        def create(self, **_kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = FakeChat()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    result = _hosted_fallback(
        messages=[{"role": "user", "content": "status"}],
        purpose="general",
        temperature=0.2,
        max_tokens=100,
        primary_error=RuntimeError("OmniRoute timeout"),
        requested_model="auto/best-fast",
    )

    assert result.text == "Hosted fallback answer"
    assert result.provider == "nvidia"
    assert result.resolved_provider == "nvidia"
    assert result.fallback_used is True
    assert result.requested_model == "auto/best-fast"
    assert result.gateway == "arch-hosted-fallback:nvidia"
    assert "OmniRoute timeout" in result.fallback_reason


def test_hosted_fallback_fails_closed_when_no_hosted_provider_is_configured(monkeypatch):
    for name in (
        "NVIDIA_API_KEY",
        "NVIDIA_API_KEY_1",
        "NVIDIA_API_KEY_2",
        "NVIDIA_API_KEY_3",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    fake_module = types.SimpleNamespace(OpenAI=object)
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    with pytest.raises(GovernanceError, match="ARCH_HOSTED_FALLBACK_EXHAUSTED"):
        _hosted_fallback(
            messages=[{"role": "user", "content": "status"}],
            purpose="general",
            temperature=0.2,
            max_tokens=100,
            primary_error=RuntimeError("primary unavailable"),
            requested_model="auto/best-fast",
        )
