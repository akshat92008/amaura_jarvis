from __future__ import annotations

import sys
import types

import pytest

from jarvis.amaura.models import GovernanceError
from jarvis.arch_provider_resilience import (
    _enabled_for,
    _fallback_specs,
    _hosted_fallback,
    _timeout_seconds,
    _total_budget_seconds,
)


def _clear_optional_cloud(monkeypatch) -> None:
    for name in (
        "NVIDIA_API_KEY",
        "NVIDIA_API_KEY_1",
        "NVIDIA_API_KEY_2",
        "NVIDIA_API_KEY_3",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "AMAURA_ARCH_NVIDIA_FALLBACK_MODEL",
        "AMAURA_ARCH_GROQ_FALLBACK_MODEL",
        "AMAURA_ARCH_OPENROUTER_FALLBACK_MODEL",
        "AMAURA_ARCH_OPENAI_FALLBACK_MODEL",
        "AMAURA_NVIDIA_MODEL",
        "AMAURA_GROQ_MODEL",
        "AMAURA_OPENROUTER_MODEL",
        "AMAURA_OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_arch_hosted_failover_is_interactive_only_and_never_local(monkeypatch):
    _clear_optional_cloud(monkeypatch)
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_COGNITION_FAILOVER", "1")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_ORDER", "nvidia,groq")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")

    assert _enabled_for("general") is True
    assert _enabled_for("planner") is False
    providers = [item[0] for item in _fallback_specs()]
    assert providers == ["nvidia", "groq"]
    assert "ollama" not in providers


def test_fallback_specs_reuse_existing_provider_model_configuration(monkeypatch):
    _clear_optional_cloud(monkeypatch)
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_ORDER", "nvidia,groq,openrouter,openai")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("AMAURA_NVIDIA_MODEL", "nvidia-model")
    monkeypatch.setenv("AMAURA_GROQ_MODEL", "groq-model")
    monkeypatch.setenv("AMAURA_OPENROUTER_MODEL", "openrouter-model")
    monkeypatch.setenv("AMAURA_OPENAI_MODEL", "openai-model")

    specs = _fallback_specs()

    assert [(provider, model) for provider, _url, _key, model in specs] == [
        ("nvidia", "nvidia-model"),
        ("groq", "groq-model"),
        ("openrouter", "openrouter-model"),
        ("openai", "openai-model"),
    ]


def test_hosted_fallback_returns_truthful_provider_provenance(monkeypatch):
    _clear_optional_cloud(monkeypatch)
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_ORDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")

    captured_kwargs = {}

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
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
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
    assert captured_kwargs["max_retries"] == 0
    assert 3.0 <= float(captured_kwargs["timeout"]) <= 20.0


def test_hosted_fallback_tries_second_provider_after_first_failure(monkeypatch):
    _clear_optional_cloud(monkeypatch)
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_ORDER", "nvidia,groq")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-secret")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_BUDGET_SECONDS", "12")

    attempted: list[str] = []

    class FakeMessage:
        content = "Second provider recovered"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]
        model = "llama-3.3-70b-versatile"

    class FakeCompletions:
        def __init__(self, provider: str):
            self.provider = provider

        def create(self, **_kwargs):
            attempted.append(self.provider)
            if self.provider == "nvidia":
                raise TimeoutError("nvidia timeout")
            return FakeResponse()

    class FakeChat:
        def __init__(self, provider: str):
            self.completions = FakeCompletions(provider)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            base_url = str(kwargs.get("base_url") or "")
            provider = "nvidia" if "nvidia" in base_url else "groq"
            assert kwargs["max_retries"] == 0
            self.chat = FakeChat(provider)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    result = _hosted_fallback(
        messages=[{"role": "user", "content": "status"}],
        purpose="general",
        temperature=0.1,
        max_tokens=100,
        primary_error=RuntimeError("primary timeout"),
        requested_model="auto/best-fast",
    )

    assert attempted == ["nvidia", "groq"]
    assert result.provider == "groq"
    assert result.text == "Second provider recovered"
    assert result.fallback_used is True


def test_hosted_fallback_timeout_and_total_budget_are_bounded(monkeypatch):
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_BUDGET_SECONDS", "999")
    assert _timeout_seconds() == 20.0
    assert _total_budget_seconds() == 30.0

    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_BUDGET_SECONDS", "0")
    assert _timeout_seconds() == 3.0
    assert _total_budget_seconds() == 6.0


def test_hosted_fallback_fails_closed_when_no_hosted_provider_is_configured(monkeypatch):
    _clear_optional_cloud(monkeypatch)
    monkeypatch.setenv("AMAURA_ARCH_HOSTED_FALLBACK_ORDER", "nvidia,groq,openrouter,openai")

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
