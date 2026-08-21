from __future__ import annotations

from types import SimpleNamespace

import pytest

import jarvis.api as api


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(api.os.environ):
        if key.startswith(("NVIDIA_API_KEY", "NVIDIA_FALLBACK_API_KEY", "NVIDIA_KEY")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(api, "_env_loaded", True)
    api.NvidiaClient._nvidia_disabled_until = 0.0


def test_nvidia_defaults_are_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "primary")
    monkeypatch.delenv("AMAURA_NVIDIA_TIMEOUT", raising=False)
    monkeypatch.delenv("NVIDIA_TIMEOUT", raising=False)
    monkeypatch.delenv("AMAURA_NVIDIA_TOTAL_TIMEOUT", raising=False)
    monkeypatch.delenv("AMAURA_NVIDIA_MAX_KEY_ATTEMPTS", raising=False)

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_kw: None))

    monkeypatch.setattr(api, "OpenAI", FakeOpenAI)
    client = api.NvidiaClient(allow_fallbacks=False)

    assert client.nv_timeout == 25.0
    assert client.nv_total_timeout == 45.0
    assert client.nv_max_key_attempts == 1


def test_nvidia_attempt_budget_caps_credential_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "primary")
    monkeypatch.setenv("NVIDIA_FALLBACK_API_KEY_1", "secondary")
    monkeypatch.setenv("NVIDIA_FALLBACK_API_KEY_2", "tertiary")
    monkeypatch.setenv("AMAURA_NVIDIA_TIMEOUT", "7")
    monkeypatch.setenv("AMAURA_NVIDIA_TOTAL_TIMEOUT", "11")
    monkeypatch.setenv("AMAURA_NVIDIA_MAX_KEY_ATTEMPTS", "2")

    calls: list[tuple[str, float]] = []

    class FailingCompletions:
        def __init__(self, key: str):
            self.key = key

        def create(self, **kwargs):
            calls.append((self.key, float(kwargs["timeout"])))
            raise RuntimeError("provider unavailable")

    class FakeOpenAI:
        def __init__(self, *, api_key: str, **_kwargs):
            self.chat = SimpleNamespace(completions=FailingCompletions(api_key))

    monkeypatch.setattr(api, "OpenAI", FakeOpenAI)
    client = api.NvidiaClient(allow_fallbacks=False)

    with pytest.raises(RuntimeError, match="provider failed"):
        client.chat_sync(model_id="meta/llama-3.3-70b-instruct", messages=[{"role": "user", "content": "ping"}])

    assert [key for key, _timeout in calls] == ["primary", "secondary"]
    assert all(1.0 <= timeout <= 7.0 for _key, timeout in calls)
    assert "tertiary" not in [key for key, _timeout in calls]
