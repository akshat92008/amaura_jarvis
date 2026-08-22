"""Regression test suite for interactive cognition resilience, provider truthfulness, and readiness gating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

import jarvis
from jarvis import ui
from jarvis.agent import JarvisAgent
from jarvis.amaura.direct_action import DirectActionRouter
from jarvis.amaura.model_gateway import (
    CognitiveModelGateway,
    CognitiveModelResult,
)
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.readiness import production_readiness
from jarvis.tools.amaura import get_control_plane, reset_control_plane


@pytest.fixture
def clean_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "amaura_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", str(data_dir / "audit.checkpoint"))
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", "a" * 64)
    monkeypatch.setenv("AMAURA_REVIEW_ATTESTATION_KEY", "r" * 64)
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", "b" * 64)
    monkeypatch.setenv("AMAURA_EVIDENCE_HMAC_KEY", "c" * 64)
    reset_control_plane()
    return get_control_plane()


# A. Free-form conversational request routes to production cognition
def test_a_free_form_conversation_routes_to_cognition(clean_control, monkeypatch):
    monkeypatch.setenv("AMAURA_JARVIS_UNIFIED_CONVERSATION_MODEL", "1")

    fake_result = CognitiveModelResult(
        text="Hello sir, I am JARVIS. How may I assist your engineering work today?",
        provider="omniroute",
        model="auto/best-fast",
        requested_model="auto/best-fast",
        resolved_provider="omniroute",
        resolved_model="auto/best-fast",
        latency_ms=120,
    )

    with patch.object(CognitiveModelGateway, "generate", return_value=fake_result):
        agent = JarvisAgent()
        res = agent.run_executive(
            "explain in two sentences what Amaura Labs is capable of",
            control=clean_control,
            session_id="test-session-a",
        )
        assert res["intent"] == "conversation"
        assert "Hello sir, I am JARVIS" in res["message"]
        prov = res.get("model_provenance", {})
        assert prov.get("provider") == "omniroute"
        assert prov.get("model") == "auto/best-fast"


# B. Interactive CLI does not directly hardwire NVIDIA when another provider is configured
def test_b_cli_does_not_hardwire_nvidia(monkeypatch):
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-mock")
    monkeypatch.setenv("AMAURA_OPENAI_MODEL", "gpt-4o-mini")

    gw_status = CognitiveModelGateway.status(purpose="general")
    assert gw_status["provider"] == "openai"
    assert gw_status["model"] == "gpt-4o-mini"
    assert gw_status["available"] is True

    agent = JarvisAgent()
    assert agent.provider == "openai"


# C. Configured primary provider works
def test_c_configured_primary_provider_works(monkeypatch):
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-mock")
    monkeypatch.setenv("AMAURA_OPENAI_MODEL", "gpt-4o-mini")

    expected = CognitiveModelResult(
        text="Primary provider response",
        provider="openai",
        model="gpt-4o-mini",
        requested_model="gpt-4o-mini",
        resolved_provider="openai",
        resolved_model="gpt-4o-mini",
        latency_ms=80,
    )

    with patch.object(CognitiveModelGateway, "_openai_compatible", return_value=expected):
        result = CognitiveModelGateway.generate(
            messages=[{"role": "user", "content": "hi"}],
            purpose="general",
        )
        assert result.provider == "openai"
        assert result.model == "gpt-4o-mini"
        assert result.text == "Primary provider response"
        assert result.fallback_used is False


# D. Bounded configured fallback works
def test_d_bounded_configured_fallback_works(monkeypatch):
    monkeypatch.setenv("AMAURA_MODEL_PROVIDER", "omniroute")
    monkeypatch.setenv("AMAURA_OMNIROUTE_API_KEY", "sk-test-omni")
    monkeypatch.setenv("AMAURA_OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
    monkeypatch.setenv("AMAURA_OMNIROUTE_CHAT_MODEL", "flaky-primary-model")
    monkeypatch.setenv("AMAURA_OMNIROUTE_FALLBACK_MODEL", "healthy-fallback-model")

    def mock_post(*args, **kwargs):
        payload = kwargs.get("json", {})
        model = payload.get("model")
        if model == "flaky-primary-model":
            import httpx

            raise httpx.TimeoutException("Primary timed out")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '{"choices": [{"message": {"content": "Fallback response online"}}]}'
        resp.headers = {"x-resolved-provider": "omniroute", "x-resolved-model": "healthy-fallback-model"}
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = MagicMock()
    mock_client.post = mock_post

    with patch.object(CognitiveModelGateway, "_http_client", return_value=mock_client):
        result = CognitiveModelGateway.generate(
            messages=[{"role": "user", "content": "hello"}],
            purpose="general",
        )
        assert result.fallback_used is True
        assert result.model == "healthy-fallback-model"
        assert "Fallback response online" in result.text


# E. All-provider failure returns controlled error, not traceback/hang
def test_e_all_provider_failure_returns_controlled_error(clean_control, monkeypatch):
    monkeypatch.setenv("AMAURA_JARVIS_UNIFIED_CONVERSATION_MODEL", "1")
    monkeypatch.setenv("AMAURA_JARVIS_INTERACTIVE_LEGACY_FALLBACK", "0")

    with patch.object(
        CognitiveModelGateway,
        "generate",
        side_effect=GovernanceError("All upstream providers unreachable"),
    ):
        agent = JarvisAgent()
        res = agent.run_executive(
            "hey jarvis how are you doing today?",
            control=clean_control,
            session_id="test-session-e",
        )
        assert res["intent"] == "conversation"
        assert "The interactive cognition service is temporarily unavailable" in res["message"]
        prov = res.get("model_provenance", {})
        assert prov.get("provider") == "unavailable"
        assert prov.get("fallback_used") is True


# F. Deterministic arithmetic still works without unnecessary model call
def test_f_deterministic_arithmetic_bypasses_model(clean_control):
    with patch.object(CognitiveModelGateway, "generate") as mock_gen:
        agent = JarvisAgent()
        res = agent.run_executive("what is 347 * 29?", control=clean_control, session_id="test-session-f")
        mock_gen.assert_not_called()
        assert "10063" in res["message"]
        prov = res.get("model_provenance", {})
        assert prov.get("provider") in ("local-arithmetic", "local_deterministic")


# G. Filesystem/app-control/direct actions still route directly
def test_g_direct_actions_route_directly(clean_control):
    direct_res = DirectActionRouter.execute("what is 19 * 23", context="", control=clean_control)
    assert direct_res is not None
    assert "437" in direct_res.output
    assert direct_res.provider in ("local-arithmetic", "local_deterministic")


# H. amaura status cannot report production_ready=true when interactive cognition is unavailable
def test_h_status_fails_closed_when_cognition_unavailable(clean_control, monkeypatch):
    with patch(
        "jarvis.amaura.readiness._probe_interactive_cognition",
        return_value={
            "ready": False,
            "provider": "omniroute",
            "requested_model": "auto/best-fast",
            "actual_model": "",
            "latency_ms": 0,
            "error": "authentication_failure",
        },
    ):
        status = production_readiness(clean_control, live=True)
        assert status["ready"] is False
        assert status["production_ready"] is False
        assert "interactive_cognition_ready" in status["blockers"]
        assert status["live_checks"]["interactive_cognition_ready"] is False


# I. Banner version = actual package version 5.5.0
def test_i_banner_version_matches_package():
    test_console = Console(record=True, width=120)
    with patch.object(ui, "console", test_console):
        ui.print_boot_sequence(
            model_name="auto/best-fast",
            provider_name="OmniRoute",
            version=jarvis.__version__,
        )
    output = test_console.export_text()
    assert f"JARVIS VERSION: {jarvis.__version__}" in output
    assert "5.5.0" in output


# J. Banner provider/model reflect actual configured interactive route
def test_j_banner_reflects_actual_configured_provider_and_model():
    test_console = Console(record=True, width=120)
    with patch.object(ui, "console", test_console):
        ui.print_boot_sequence(
            model_name="custom-model-99",
            provider_name="CustomProviderGateway",
            version="5.5.0",
        )
    output = test_console.export_text()
    assert "Interactive Provider: CustomProviderGateway" in output
    assert "INTERACTIVE PROVIDER: CustomProviderGateway" in output
    assert "INTERACTIVE MODEL: custom-model-99" in output
    assert "Connecting to CustomProviderGateway cognition gateway" in output
    assert "Powered by NVIDIA • v1.0.0" not in output
