from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.arch import _parse_args
from jarvis.arch_macos_service import DEFAULT_LABEL, LEGACY_LABELS, launch_agent_payload


def _runtime_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    env_file = root / ".env.amaura"
    env_file.write_text("AMAURA_OPERATOR_KEY=test\n", encoding="utf-8")
    env_file.chmod(0o600)
    return root


def test_arch_launch_agent_runs_only_unified_headless_runtime(tmp_path):
    root = _runtime_root(tmp_path)
    payload = launch_agent_payload(root)

    assert payload["Label"] == "com.amaura.arch"
    args = payload["ProgramArguments"]
    assert args[:3] == [str(root / ".venv" / "bin" / "python"), "-m", "jarvis.arch"]
    assert "--headless" in args
    assert "--no-web" in args
    rendered = repr(payload)
    assert "jarvis.amaura.company_daemon" not in rendered
    assert "amaura-company" not in rendered
    assert all(label not in rendered for label in LEGACY_LABELS)


def test_arch_launch_agent_rejects_public_env_file(tmp_path):
    root = _runtime_root(tmp_path)
    (root / ".env.amaura").chmod(0o644)
    with pytest.raises(PermissionError, match="chmod 600"):
        launch_agent_payload(root)


def test_arch_launch_agent_label_cannot_fork_second_runtime(tmp_path):
    root = _runtime_root(tmp_path)
    with pytest.raises(ValueError, match=DEFAULT_LABEL):
        launch_agent_payload(root, label="com.example.second-arch")


def test_arch_headless_cli_contract():
    args = _parse_args(["--headless", "--no-web"])
    assert args.headless is True
    assert args.no_web is True


def test_arch_headless_rejects_prompt_and_voice():
    with pytest.raises(SystemExit):
        _parse_args(["do something", "--headless"])
    with pytest.raises(SystemExit):
        _parse_args(["--headless", "--voice"])
