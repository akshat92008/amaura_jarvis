from __future__ import annotations

import os
import plistlib
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.amaura.macos_service import launch_agent_payload, write_launch_agent


def test_launch_agent_payload_contains_no_credentials():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "Launch_Amaura.command").write_text("#!/bin/zsh\n")
        payload = launch_agent_payload(root)
        encoded = plistlib.dumps(payload)
        assert payload["ProgramArguments"] == ["/bin/zsh", str(root / "Launch_Amaura.command")]
        assert payload["WorkingDirectory"] == str(root)
        assert payload["KeepAlive"] == {"SuccessfulExit": False}
        assert b"API_KEY" not in encoded
        assert b"TOKEN" not in encoded
        assert b"PASSWORD" not in encoded


def test_write_launch_agent_is_valid_private_plist():
    with TemporaryDirectory() as temp:
        root = Path(temp) / "repo"
        root.mkdir()
        (root / "Launch_Amaura.command").write_text("#!/bin/zsh\n")
        destination = Path(temp) / "agent.plist"
        written = write_launch_agent(root, destination=destination)
        payload = plistlib.loads(written.read_bytes())
        assert payload["Label"] == "com.amaura.company-os"
        assert payload["RunAtLoad"] is True
        if os.name == "posix":
            assert written.stat().st_mode & 0o777 == 0o600
