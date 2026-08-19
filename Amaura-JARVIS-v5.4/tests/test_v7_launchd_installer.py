from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.install_v7_launchd as installer
from scripts.install_v7_launchd import LABEL, _payload


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    python = repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    env_file = repo / ".env.amaura"
    env_file.write_text("AMAURA_OPERATOR_KEY=secret-that-must-not-enter-plist\n", encoding="utf-8")
    env_file.chmod(0o600)
    return repo


def _completed(args: tuple[str, ...], returncode: int = 0, *, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(["launchctl", *args], returncode, stdout=stdout, stderr=stderr)


def _canonical_print() -> str:
    return f"service = {LABEL}\n\tpid = 4242\n"


def test_launchd_payload_contains_no_authority_secret_and_defaults_to_one_worker(tmp_path):
    repo = _repo(tmp_path)
    payload = _payload(repo, poll_seconds=30)
    rendered = repr(payload)
    assert payload["Label"] == LABEL
    assert payload["ProgramArguments"][0] == str(repo / ".venv" / "bin" / "python")
    assert "jarvis.amaura.company_daemon" in payload["ProgramArguments"]
    assert "--max-work-units" in payload["ProgramArguments"]
    max_index = payload["ProgramArguments"].index("--max-work-units")
    assert payload["ProgramArguments"][max_index + 1] == "1"
    assert "secret-that-must-not-enter-plist" not in rendered
    assert str(repo / ".env.amaura") in payload["ProgramArguments"]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}


def test_launchd_payload_rejects_non_private_env_file(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".env.amaura").chmod(0o644)
    with pytest.raises(RuntimeError, match="chmod 600"):
        _payload(repo, poll_seconds=30)


def test_install_migrates_obsolete_service_after_verification(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    legacy = launch_agents / f"{installer.LEGACY_LABEL}.plist"
    legacy.write_text("legacy", encoding="utf-8")
    calls = []

    def fake_launchctl(*args: str):
        calls.append(args)
        if args[:1] == ("print",) and args[-1].endswith(LABEL):
            return _completed(args, stdout=_canonical_print())
        if args[:1] == ("print",) and args[-1].endswith(installer.LEGACY_LABEL):
            return _completed(args, returncode=113, stderr="Could not find service")
        return _completed(args)

    monkeypatch.setattr(installer, "_launchctl", fake_launchctl)
    assert installer.install(repo, poll_seconds=30, dry_run=False) == 0
    assert (launch_agents / f"{LABEL}.plist").exists()
    assert not legacy.exists()
    assert any(call[0] == "print" and call[-1].endswith(LABEL) for call in calls)
    assert any(call[0] == "print" and call[-1].endswith(installer.LEGACY_LABEL) for call in calls)


def test_install_rejects_service_without_running_pid_and_rolls_back(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    legacy = launch_agents / f"{installer.LEGACY_LABEL}.plist"
    legacy.write_bytes(b"legacy-service")

    def fake_launchctl(*args: str):
        if args[:1] == ("print",) and args[-1].endswith(LABEL):
            return _completed(args, stdout=f"service = {LABEL}\nstate = waiting\n")
        if args[:1] == ("print",) and args[-1].endswith(installer.LEGACY_LABEL):
            return _completed(args, returncode=113, stderr="Could not find service")
        return _completed(args)

    monkeypatch.setattr(installer, "_launchctl", fake_launchctl)
    with pytest.raises(RuntimeError, match="running PID"):
        installer.install(repo, poll_seconds=30, dry_run=False)
    assert not (launch_agents / f"{LABEL}.plist").exists()
    assert legacy.exists()


def test_install_failure_restores_previous_canonical_service(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    canonical = launch_agents / f"{LABEL}.plist"
    canonical.write_bytes(b"previous-canonical")
    legacy = launch_agents / f"{installer.LEGACY_LABEL}.plist"
    legacy.write_bytes(b"legacy-service")
    kickstarts = [0]

    def fake_launchctl(*args: str):
        if args[0] == "kickstart":
            kickstarts[0] += 1
            if kickstarts[0] == 1:
                return _completed(args, returncode=1, stderr="simulated kickstart failure")
        return _completed(args, stdout=_canonical_print() if args[0] == "print" else "")

    monkeypatch.setattr(installer, "_launchctl", fake_launchctl)
    with pytest.raises(RuntimeError, match="kickstart failed"):
        installer.install(repo, poll_seconds=30, dry_run=False)
    assert canonical.read_bytes() == b"previous-canonical"
    assert legacy.exists()
    assert kickstarts[0] >= 2
