from __future__ import annotations

import os
import plistlib
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.amaura.macos_service import DEFAULT_LABEL, launch_agent_payload, write_launch_agent


def _repo(root: Path) -> Path:
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    env_file = root / ".env.amaura"
    env_file.write_text("AMAURA_OPERATOR_KEY=not-embedded-in-plist\n", encoding="utf-8")
    env_file.chmod(0o600)
    return root


def test_legacy_amaura_service_api_routes_only_to_canonical_arch():
    with TemporaryDirectory() as temp:
        root = _repo(Path(temp).resolve())
        payload = launch_agent_payload(root, poll_seconds=30)
        encoded = plistlib.dumps(payload)
        args = payload["ProgramArguments"]

        assert payload["Label"] == "com.amaura.arch" == DEFAULT_LABEL
        assert args[0] == str(root / ".venv" / "bin" / "python")
        assert args[1:3] == ["-m", "jarvis.arch"]
        assert "--headless" in args
        assert "--no-web" in args
        assert "jarvis.amaura.company_daemon" not in args
        assert str(root / ".env.amaura") in args
        assert payload["WorkingDirectory"] == str(root)
        assert payload["KeepAlive"] == {"SuccessfulExit": False}
        assert b"not-embedded-in-plist" not in encoded
        assert b"API_KEY" not in encoded
        assert b"TOKEN" not in encoded
        assert b"PASSWORD" not in encoded


def test_legacy_write_launch_agent_writes_private_arch_plist():
    with TemporaryDirectory() as temp:
        root = _repo(Path(temp) / "repo")
        destination = Path(temp) / "agent.plist"
        written = write_launch_agent(root, destination=destination, poll_seconds=30)
        payload = plistlib.loads(written.read_bytes())

        assert payload["Label"] == DEFAULT_LABEL
        assert "jarvis.arch" in payload["ProgramArguments"]
        assert "jarvis.amaura.company_daemon" not in payload["ProgramArguments"]
        assert payload["RunAtLoad"] is True
        if os.name == "posix":
            assert written.stat().st_mode & 0o777 == 0o600


def test_legacy_service_api_rejects_non_private_environment_file():
    with TemporaryDirectory() as temp:
        root = _repo(Path(temp).resolve())
        (root / ".env.amaura").chmod(0o644)
        try:
            launch_agent_payload(root)
        except PermissionError as exc:
            assert "chmod 600" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("canonical ARCH LaunchAgent must reject a non-private env file")
