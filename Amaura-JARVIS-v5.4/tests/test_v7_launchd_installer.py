from __future__ import annotations

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


def test_retired_v7_payload_emits_only_canonical_arch(tmp_path):
    repo = _repo(tmp_path)
    payload = _payload(repo, poll_seconds=30)
    rendered = repr(payload)
    args = payload["ProgramArguments"]

    assert payload["Label"] == "com.amaura.arch" == LABEL
    assert args[0] == str(repo / ".venv" / "bin" / "python")
    assert args[1:3] == ["-m", "jarvis.arch"]
    assert "--headless" in args
    assert "--no-web" in args
    assert "jarvis.amaura.company_daemon" not in args
    assert "secret-that-must-not-enter-plist" not in rendered
    assert str(repo / ".env.amaura") in args
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}


def test_retired_v7_payload_rejects_non_private_env_file(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".env.amaura").chmod(0o644)
    with pytest.raises(RuntimeError, match="chmod 600"):
        _payload(repo, poll_seconds=30)


def test_retired_v7_install_delegates_to_arch_installer(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    seen = {}

    def fake_install(repo_root: Path, *, dry_run: bool):
        seen["repo"] = repo_root
        seen["dry_run"] = dry_run
        return 17

    monkeypatch.setattr(installer._arch, "install", fake_install)
    assert installer.install(repo, poll_seconds=999, dry_run=True) == 17
    assert seen == {"repo": repo, "dry_run": True}


def test_retired_v7_uninstall_delegates_to_arch_installer(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    seen = {}

    def fake_uninstall(repo_root: Path, *, dry_run: bool):
        seen["repo"] = repo_root
        seen["dry_run"] = dry_run
        return 23

    monkeypatch.setattr(installer._arch, "uninstall", fake_uninstall)
    assert installer.uninstall(repo, dry_run=False) == 23
    assert seen == {"repo": repo, "dry_run": False}
