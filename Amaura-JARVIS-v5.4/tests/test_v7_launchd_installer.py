from __future__ import annotations

from pathlib import Path

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

    try:
        _payload(repo, poll_seconds=30)
    except RuntimeError as exc:
        assert "chmod 600" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("launchd payload must reject a non-private Amaura env file")
