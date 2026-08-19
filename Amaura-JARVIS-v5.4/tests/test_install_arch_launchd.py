from __future__ import annotations

import importlib.util
import plistlib
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_arch_launchd.py"
SPEC = importlib.util.spec_from_file_location("install_arch_launchd", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
install_arch_launchd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install_arch_launchd)


def _cp(*args: str, rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["launchctl", *args], rc, stdout, stderr)


def test_wait_for_service_polls_launchd_and_health_without_kickstart(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_launchctl(*args: str):
        calls.append(args)
        return _cp(*args, stdout="com.amaura.arch = {\n    pid = 32172\n}")

    monkeypatch.setattr(install_arch_launchd, "_launchctl", fake_launchctl)
    monkeypatch.setattr(install_arch_launchd, "_health_ok", lambda: True)
    monkeypatch.setattr(install_arch_launchd.time, "sleep", lambda _seconds: None)

    pid = install_arch_launchd._wait_for_service(domain="gui/501", timeout=0.2)

    assert pid == 32172
    assert calls == [("print", "gui/501/com.amaura.arch")]
    assert all("kickstart" not in call for call in calls)


def test_install_uses_bootstrap_enable_and_read_only_verification(monkeypatch, tmp_path):
    monkeypatch.setattr(install_arch_launchd.sys, "platform", "darwin")

    canonical = tmp_path / "LaunchAgents" / "com.amaura.arch.plist"
    monkeypatch.setattr(install_arch_launchd, "_canonical_plist", lambda: canonical)
    monkeypatch.setattr(install_arch_launchd, "_legacy_plists", lambda: {})

    payload = {
        "Label": "com.amaura.arch",
        "ProgramArguments": ["/tmp/python", "-m", "jarvis.arch", "--headless", "--no-web"],
        "RunAtLoad": True,
    }
    monkeypatch.setattr(install_arch_launchd, "launch_agent_payload", lambda _root: payload)
    monkeypatch.setattr(install_arch_launchd, "load_amaura_env", lambda *_args, **_kwargs: None)

    calls: list[tuple[str, ...]] = []

    def fake_launchctl(*args: str):
        calls.append(args)
        return _cp(*args)

    monkeypatch.setattr(install_arch_launchd, "_launchctl", fake_launchctl)

    def fake_verify(*, domain: str, canonical: Path, expected_payload: dict) -> int:
        assert domain.startswith("gui/")
        assert plistlib.loads(canonical.read_bytes()) == expected_payload
        return 32172

    monkeypatch.setattr(install_arch_launchd, "_verify_installed_service", fake_verify)

    assert install_arch_launchd.install(tmp_path, dry_run=False) == 0
    assert any(call[0] == "bootstrap" for call in calls)
    assert any(call[0] == "enable" for call in calls)
    assert all(call[0] != "kickstart" for call in calls)


def test_wait_for_service_times_out_when_pid_never_appears(monkeypatch):
    monkeypatch.setattr(
        install_arch_launchd,
        "_launchctl",
        lambda *args: _cp(*args, stdout="com.amaura.arch = { state = waiting }")
    )
    monkeypatch.setattr(install_arch_launchd.time, "sleep", lambda _seconds: None)

    ticks = iter([0.0, 0.0, 1.0, 1.0])
    monkeypatch.setattr(install_arch_launchd.time, "monotonic", lambda: next(ticks, 1.0))

    with pytest.raises(RuntimeError, match="did not become healthy"):
        install_arch_launchd._wait_for_service(domain="gui/501", timeout=0.5)
