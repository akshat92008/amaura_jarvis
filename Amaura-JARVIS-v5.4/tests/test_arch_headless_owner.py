from __future__ import annotations

import pytest

import jarvis.arch as arch
import jarvis.cli as cli
import jarvis.network_security as network_security


def test_headless_backend_runs_in_owner_process_and_fails_if_server_returns(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, object]] = []
    monkeypatch.setenv("JARVIS_HOST", "127.0.0.1")
    monkeypatch.setenv("JARVIS_PORT", "8765")
    monkeypatch.setattr(network_security, "validate_bind_security", lambda host: calls.append(("validate", host)))
    monkeypatch.setattr(cli, "_run_web_server", lambda host, port: calls.append(("server", (host, port))))

    with pytest.raises(RuntimeError, match="launchd can recover"):
        arch._run_headless_server()

    assert calls == [("validate", "127.0.0.1"), ("server", ("127.0.0.1", 8765))]


def test_arch_runtime_uses_bounded_8gb_and_hosted_failover_defaults(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "ARCH_RUNTIME",
        "AMAURA_JARVIS_PROACTIVE",
        "AMAURA_JARVIS_MISSION_RUNNER",
        "AMAURA_COMPANY_AUTOPILOT_RUNTIME",
        "AMAURA_ARCH_HOSTED_COGNITION_FAILOVER",
        "AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS",
        "AMAURA_COMPANY_AUTOPILOT_WORK_UNITS",
        "AMAURA_RAM_ABSOLUTE_LIMIT_MB",
    ):
        monkeypatch.delenv(name, raising=False)

    arch.configure_arch_runtime()

    assert arch.os.environ["ARCH_RUNTIME"] == "1"
    assert arch.os.environ["AMAURA_JARVIS_PROACTIVE"] == "1"
    assert arch.os.environ["AMAURA_JARVIS_MISSION_RUNNER"] == "1"
    assert arch.os.environ["AMAURA_COMPANY_AUTOPILOT_RUNTIME"] == "1"
    assert arch.os.environ["AMAURA_ARCH_HOSTED_COGNITION_FAILOVER"] == "1"
    assert arch.os.environ["AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS"] == "12"
    assert arch.os.environ["AMAURA_COMPANY_AUTOPILOT_WORK_UNITS"] == "1"
    assert arch.os.environ["AMAURA_RAM_ABSOLUTE_LIMIT_MB"] == "2048"
